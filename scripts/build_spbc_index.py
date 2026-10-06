#!/usr/bin/env python3

import argparse
import csv
import gzip
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

#=============================================================
#
#        Script:  longairrwhitelist.sh
#         Usage:  Internal script used in 'longairrwhitelist.sh/longairrwhitelist build-index'
#
#   DESCRIPTION:  Build a sequence-centric Visium HD 3' SPBC SQLite index 
#                 from a SpaceRanger BAM. The output from this script is a 
#                 LongAIRR-ready SQLite index mapping observed raw Space Ranger CR tags to
#                 corrected Visium HD CB identifiers.
#                 
#                 SQLite tables:
#                     spbc_lookup          runtime lookup used by LongAIRR
#                     observed_pairs       all observed raw_spbc -> spbc_id evidence
#                     ambiguous_raw_spbc   excluded raw_spbc sequences mapping to multiple spbc_ids
#                     metadata             minimal run metadata and summary counts
#
#        AUTHOR:  Jonas Schuck, jschuckdev@gmail.com
#    BUG-REPORT:  
#
#=============================================================


TOOL_NAME = "longairrwhitelist build-index"
TOOL_VERSION = os.environ.get("LONGAIRR_WHITELIST_VERSION", "unknown")
FORMAT_VERSION = "longairr_whitelist_visiumhd_spbc_index_v1"
SCHEMA_VERSION = "1"

CB_RE = re.compile(r"^s_([0-9]+um)_([0-9]+)_([0-9]+)-1$")
ACGT_RE = re.compile(r"^[ACGT]+$")


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def parse_cb(cb: str) -> Optional[Tuple[str, int, int]]:
    match = CB_RE.match(cb)
    if match is None:
        return None
    return match.group(1), int(match.group(2)), int(match.group(3))


def make_spbc_id(resolution: str, x: int, y: int) -> str:
    return f"s_{resolution}_{x:05d}_{y:05d}-1"


def remove_sqlite_files(path: str) -> None:
    for suffix in ("", "-journal", "-wal", "-shm"):
        candidate = path + suffix
        if os.path.exists(candidate):
            os.remove(candidate)


def default_out_prefix(sqlite_path: str) -> str:
    path = Path(sqlite_path)
    if path.suffix.lower() in {".sqlite", ".sqlite3", ".db"}:
        return str(path.with_suffix(""))
    return str(path)


def open_text_maybe_gzip(path: str, mode: str = "wt"):
    if path.endswith(".gz"):
        return gzip.open(path, mode, newline="")
    return open(path, mode, newline="")


def scalar(conn: sqlite3.Connection, sql: str, params: Tuple = ()):  # noqa: ANN001
    row = conn.execute(sql, params).fetchone()
    return row[0] if row is not None else None


def dict_from_two_cols(conn: sqlite3.Connection, sql: str, params: Tuple = ()) -> Dict:
    return {key: value for key, value in conn.execute(sql, params).fetchall()}


# ----------------------------SQLite setup--------------------------------------

def init_db(path: str, force: bool = False) -> sqlite3.Connection:
    path = os.path.expanduser(path)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)

    if os.path.exists(path):
        if not force:
            raise SystemExit(f"Output database already exists: {path} ; use --force to overwrite")
        remove_sqlite_files(path)

    conn = sqlite3.connect(path, timeout=60)
    conn.execute("PRAGMA busy_timeout = 60000")
    conn.execute("PRAGMA journal_mode = DELETE")
    conn.execute("PRAGMA synchronous = OFF")
    conn.execute("PRAGMA temp_store = FILE")
    conn.execute("PRAGMA cache_size = -200000")

    conn.execute(
        """
        CREATE TABLE observed_pairs (
            raw_spbc TEXT NOT NULL,
            spbc_id TEXT NOT NULL,
            resolution TEXT NOT NULL,
            x INTEGER NOT NULL,
            y INTEGER NOT NULL,
            raw_spbc_len INTEGER NOT NULL,
            read_count INTEGER NOT NULL,
            PRIMARY KEY (raw_spbc, spbc_id)
        ) WITHOUT ROWID
        """
    )

    conn.execute(
        """
        CREATE TABLE metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        ) WITHOUT ROWID
        """
    )

    conn.commit()
    return conn


# ------------------------------BAM/SAM streaming-------------------------------

def parse_cr_cb_from_sam_fields(
    fields: List[str],
    cr_tag: str,
    cb_tag: str,
) -> Tuple[Optional[str], Optional[str]]:
    cr = None
    cb = None
    cr_prefix = f"{cr_tag}:Z:"
    cb_prefix = f"{cb_tag}:Z:"

    for tag in fields[11:]:
        if tag.startswith(cr_prefix):
            cr = tag[len(cr_prefix):]
        elif tag.startswith(cb_prefix):
            cb = tag[len(cb_prefix):]

    return cr, cb


def flush_counts(conn: sqlite3.Connection, pair_counts: Counter) -> None:
    if not pair_counts:
        return

    rows = [
        (raw_spbc, spbc_id, resolution, x, y, raw_spbc_len, count)
        for (raw_spbc, spbc_id, resolution, x, y, raw_spbc_len), count in pair_counts.items()
    ]

    conn.executemany(
        """
        INSERT INTO observed_pairs(
            raw_spbc, spbc_id, resolution, x, y, raw_spbc_len, read_count
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(raw_spbc, spbc_id)
        DO UPDATE SET read_count = read_count + excluded.read_count
        """,
        rows,
    )
    conn.commit()
    pair_counts.clear()


def stream_bam_with_samtools(args: argparse.Namespace, conn: sqlite3.Connection):
    cmd = [args.samtools, "view", "-@", str(args.threads), args.bam]
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1024 * 1024,
    )

    pair_counts = Counter()
    stats = Counter()
    length_read_counts = Counter()
    start = time.time()

    assert proc.stdout is not None
    for line in proc.stdout:
        stats["reads_seen"] += 1

        fields = line.rstrip("\n").split("\t")
        if len(fields) < 12:
            stats["malformed_sam_lines"] += 1
        else:
            cr, cb = parse_cr_cb_from_sam_fields(
                fields,
                cr_tag=args.cr_tag,
                cb_tag=args.cb_tag,
            )

            if cr is None:
                stats["missing_cr"] += 1
            elif cb is None:
                stats["missing_cb"] += 1
            else:
                stats["reads_with_cr_cb_tags"] += 1
                cr = cr.upper()

                if not ACGT_RE.fullmatch(cr):
                    stats["invalid_cr_sequence"] += 1
                else:
                    parsed = parse_cb(cb)
                    if parsed is None:
                        stats["invalid_cb"] += 1
                    else:
                        resolution, x, y = parsed
                        spbc_id = make_spbc_id(resolution, x, y)
                        raw_spbc_len = len(cr)

                        stats["reads_with_valid_cr_cb"] += 1
                        length_read_counts[raw_spbc_len] += 1

                        if args.filter_lengths and raw_spbc_len not in args.allowed_lengths:
                            stats["filtered_length"] += 1
                        else:
                            stats["reads_used_for_index"] += 1
                            pair_counts[(cr, spbc_id, resolution, x, y, raw_spbc_len)] += 1

        if len(pair_counts) >= args.chunk_unique:
            flush_counts(conn, pair_counts)

        if args.progress and stats["reads_seen"] % args.progress == 0:
            elapsed = max(time.time() - start, 1)
            rate = stats["reads_seen"] / elapsed
            print(
                f"[INFO] {stats['reads_seen']:,} reads seen | "
                f"{stats['reads_used_for_index']:,} used for index | "
                f"{rate:,.0f} reads/s",
                file=sys.stderr,
            )

        if args.max_reads and stats["reads_seen"] >= args.max_reads:
            proc.terminate()
            break

    flush_counts(conn, pair_counts)

    stderr = proc.stderr.read() if proc.stderr is not None else ""
    rc = proc.wait()
    if rc not in (0, -15):
        print(stderr, file=sys.stderr)
        raise SystemExit(f"samtools failed with exit code {rc}")

    elapsed = max(time.time() - start, 1)
    stats["streaming_seconds"] = round(elapsed, 3)
    stats["streaming_reads_per_second"] = round(stats["reads_seen"] / elapsed, 3)

    return stats, length_read_counts


# ------------------------------Index building----------------------------------


def build_sequence_centric_tables(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE INDEX IF NOT EXISTS observed_pairs_spbc_id_idx ON observed_pairs(spbc_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS observed_pairs_len_idx ON observed_pairs(raw_spbc_len)")
    conn.commit()

    conn.execute("DROP TABLE IF EXISTS spbc_lookup")
    conn.execute(
        """
        CREATE TABLE spbc_lookup (
            raw_spbc TEXT PRIMARY KEY,
            spbc_id TEXT NOT NULL,
            resolution TEXT NOT NULL,
            x INTEGER NOT NULL,
            y INTEGER NOT NULL,
            raw_spbc_len INTEGER NOT NULL,
            read_count INTEGER NOT NULL
        ) WITHOUT ROWID
        """
    )
    conn.execute(
        """
        INSERT INTO spbc_lookup(
            raw_spbc, spbc_id, resolution, x, y, raw_spbc_len, read_count
        )
        SELECT
            op.raw_spbc,
            op.spbc_id,
            op.resolution,
            op.x,
            op.y,
            op.raw_spbc_len,
            op.read_count
        FROM observed_pairs op
        JOIN (
            SELECT raw_spbc
            FROM observed_pairs
            GROUP BY raw_spbc
            HAVING COUNT(*) = 1
        ) unique_raw
          ON unique_raw.raw_spbc = op.raw_spbc
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS spbc_lookup_len_idx ON spbc_lookup(raw_spbc_len)")
    conn.execute("CREATE INDEX IF NOT EXISTS spbc_lookup_spbc_id_idx ON spbc_lookup(spbc_id)")
    conn.commit()

    conn.execute("DROP TABLE IF EXISTS ambiguous_raw_spbc")
    conn.execute(
        """
        CREATE TABLE ambiguous_raw_spbc (
            raw_spbc TEXT NOT NULL,
            spbc_id TEXT NOT NULL,
            resolution TEXT NOT NULL,
            x INTEGER NOT NULL,
            y INTEGER NOT NULL,
            raw_spbc_len INTEGER NOT NULL,
            read_count INTEGER NOT NULL,
            n_spbc_ids INTEGER NOT NULL,
            total_read_count INTEGER NOT NULL,
            pair_fraction REAL NOT NULL,
            PRIMARY KEY (raw_spbc, spbc_id)
        ) WITHOUT ROWID
        """
    )
    conn.execute(
        """
        INSERT INTO ambiguous_raw_spbc(
            raw_spbc, spbc_id, resolution, x, y, raw_spbc_len, read_count,
            n_spbc_ids, total_read_count, pair_fraction
        )
        SELECT
            op.raw_spbc,
            op.spbc_id,
            op.resolution,
            op.x,
            op.y,
            op.raw_spbc_len,
            op.read_count,
            amb.n_spbc_ids,
            amb.total_read_count,
            CAST(op.read_count AS REAL) / amb.total_read_count AS pair_fraction
        FROM observed_pairs op
        JOIN (
            SELECT raw_spbc, COUNT(*) AS n_spbc_ids, SUM(read_count) AS total_read_count
            FROM observed_pairs
            GROUP BY raw_spbc
            HAVING COUNT(*) > 1
        ) amb
          ON amb.raw_spbc = op.raw_spbc
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS ambiguous_raw_spbc_len_idx ON ambiguous_raw_spbc(raw_spbc_len)")
    conn.execute("CREATE INDEX IF NOT EXISTS ambiguous_raw_spbc_spbc_id_idx ON ambiguous_raw_spbc(spbc_id)")
    conn.commit()


def validate_sqlite_index(conn: sqlite3.Connection) -> None:
    ambiguous_in_lookup = scalar(
        conn,
        """
        SELECT COUNT(*)
        FROM spbc_lookup l
        JOIN (
            SELECT raw_spbc
            FROM observed_pairs
            GROUP BY raw_spbc
            HAVING COUNT(*) > 1
        ) amb
          ON amb.raw_spbc = l.raw_spbc
        """,
    )
    if ambiguous_in_lookup:
        raise SystemExit(
            f"Internal consistency error: {ambiguous_in_lookup} ambiguous raw SPBCs are present in spbc_lookup"
        )

    missing_lookup_rows = scalar(
        conn,
        """
        SELECT COUNT(*)
        FROM (
            SELECT raw_spbc
            FROM observed_pairs
            GROUP BY raw_spbc
            HAVING COUNT(*) = 1
        ) unique_raw
        LEFT JOIN spbc_lookup l ON l.raw_spbc = unique_raw.raw_spbc
        WHERE l.raw_spbc IS NULL
        """,
    )
    if missing_lookup_rows:
        raise SystemExit(
            f"Internal consistency error: {missing_lookup_rows} unique raw SPBCs are missing from spbc_lookup"
        )

    lookup_rows = scalar(conn, "SELECT COUNT(*) FROM spbc_lookup") or 0
    if lookup_rows == 0:
        raise SystemExit("No entries were written to spbc_lookup. Check BAM tags and filtering settings.")



# ------------------------------Summary output----------------------------------


def collect_summary(conn: sqlite3.Connection, args: argparse.Namespace, stats: Counter, length_read_counts: Counter) -> Dict:
    database_counts = {
        "observed_pairs": scalar(conn, "SELECT COUNT(*) FROM observed_pairs"),
        "raw_spbc_total": scalar(conn, "SELECT COUNT(DISTINCT raw_spbc) FROM observed_pairs"),
        "raw_spbc_in_lookup": scalar(conn, "SELECT COUNT(*) FROM spbc_lookup"),
        "ambiguous_raw_spbc": scalar(conn, "SELECT COUNT(DISTINCT raw_spbc) FROM ambiguous_raw_spbc"),
        "ambiguous_raw_spbc_pairs": scalar(conn, "SELECT COUNT(*) FROM ambiguous_raw_spbc"),
        "spbc_id_total_observed": scalar(conn, "SELECT COUNT(DISTINCT spbc_id) FROM observed_pairs"),
        "spbc_id_total_lookup": scalar(conn, "SELECT COUNT(DISTINCT spbc_id) FROM spbc_lookup"),
    }

    raw_total = database_counts["raw_spbc_total"] or 0
    lookup_raw = database_counts["raw_spbc_in_lookup"] or 0
    ambig_raw = database_counts["ambiguous_raw_spbc"] or 0

    summary = {
        "read_stats": dict(stats),
        "database_counts": database_counts,
        "fractions": {
            "lookup_raw_spbc_fraction": (lookup_raw / raw_total) if raw_total else None,
            "ambiguous_raw_spbc_fraction": (ambig_raw / raw_total) if raw_total else None,
        },
        "observed_cr_length_read_counts": dict(sorted(length_read_counts.items())),
        "observed_pair_length_counts": dict_from_two_cols(
            conn,
            """
            SELECT raw_spbc_len, COUNT(*)
            FROM observed_pairs
            GROUP BY raw_spbc_len
            ORDER BY raw_spbc_len
            """,
        ),
        "lookup_length_counts": dict_from_two_cols(
            conn,
            """
            SELECT raw_spbc_len, COUNT(*)
            FROM spbc_lookup
            GROUP BY raw_spbc_len
            ORDER BY raw_spbc_len
            """,
        ),
        "ambiguous_length_counts": dict_from_two_cols(
            conn,
            """
            SELECT raw_spbc_len, COUNT(DISTINCT raw_spbc)
            FROM ambiguous_raw_spbc
            GROUP BY raw_spbc_len
            ORDER BY raw_spbc_len
            """,
        ),
        "settings": {
            "cr_tag": args.cr_tag,
            "cb_tag": args.cb_tag,
            "allowed_lengths": args.allowed_lengths,
            "filter_lengths": bool(args.filter_lengths),
            "ambiguity_policy": "exclude_raw_spbc_mapping_to_multiple_spbc_ids_from_spbc_lookup",
        },
    }

    if args.allowed_lengths:
        placeholders = ",".join("?" for _ in args.allowed_lengths)
        summary["allowed_length_summary"] = {
            "allowed_lengths": args.allowed_lengths,
            "observed_pairs_with_allowed_length": scalar(
                conn,
                f"SELECT COUNT(*) FROM observed_pairs WHERE raw_spbc_len IN ({placeholders})",
                tuple(args.allowed_lengths),
            ),
            "lookup_entries_with_allowed_length": scalar(
                conn,
                f"SELECT COUNT(*) FROM spbc_lookup WHERE raw_spbc_len IN ({placeholders})",
                tuple(args.allowed_lengths),
            ),
        }

    return summary


def write_summary_json(prefix: str, args: argparse.Namespace, summary: Dict) -> str:
    path = prefix + ".summary.json"
    payload = {
        "script": Path(__file__).name,
        "format": FORMAT_VERSION,
        "schema_version": SCHEMA_VERSION,
        "tool_version": TOOL_VERSION,
        "created_at": now_iso(),
        "inputs": {
            "bam": args.bam,
            "sqlite": args.sqlite,
            "max_reads": args.max_reads,
            "reader": "samtools",
        },
        **summary,
    }
    with open(path, "w") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
    return path


def write_qc_tsv(prefix: str, summary: Dict) -> str:
    path = prefix + ".qc.tsv"
    with open(path, "w", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow(["section", "value", "count"])

        for key, value in sorted(summary.get("read_stats", {}).items()):
            writer.writerow(["read_stats", key, value])

        for key, value in sorted(summary.get("database_counts", {}).items()):
            writer.writerow(["database_counts", key, value])

        for key, value in sorted(summary.get("fractions", {}).items()):
            writer.writerow(["fractions", key, "NA" if value is None else f"{value:.6g}"])

        length_sections = [
            ("observed_cr_length_reads", summary.get("observed_cr_length_read_counts", {})),
            ("observed_pair_length", summary.get("observed_pair_length_counts", {})),
            ("lookup_length", summary.get("lookup_length_counts", {})),
            ("ambiguous_raw_spbc_length", summary.get("ambiguous_length_counts", {})),
        ]
        for section, values in length_sections:
            for key, value in sorted(values.items(), key=lambda item: int(item[0])):
                writer.writerow([section, key, value])

        for key, value in sorted(summary.get("allowed_length_summary", {}).items()):
            if isinstance(value, list):
                value = ",".join(map(str, value))
            writer.writerow(["allowed_length_summary", key, value])

    return path


def write_metadata(conn: sqlite3.Connection, args: argparse.Namespace, summary: Dict) -> None:
    entries = {
        "format": FORMAT_VERSION,
        "schema_version": SCHEMA_VERSION,
        "tool_version": TOOL_VERSION,
        "created_by": Path(__file__).name,
        "created_at": now_iso(),
        "source_bam": os.path.abspath(os.path.expanduser(args.bam)),
        "cr_tag": args.cr_tag,
        "cb_tag": args.cb_tag,
        "allowed_lengths": ",".join(map(str, args.allowed_lengths)) if args.allowed_lengths else "",
        "filter_lengths": str(bool(args.filter_lengths)),
        "ambiguity_policy": "exclude_from_runtime_lookup",
    }

    for key, value in summary.get("database_counts", {}).items():
        entries[f"qc_{key}"] = str(value)
    for key, value in summary.get("fractions", {}).items():
        entries[f"qc_{key}"] = "NA" if value is None else str(value)

    conn.executemany(
        "INSERT OR REPLACE INTO metadata(key, value) VALUES (?, ?)",
        [(key, str(value)) for key, value in entries.items()],
    )
    conn.commit()


# -----------------------------Optional TSV export-----------------------------

def export_table(conn: sqlite3.Connection, table: str, path: str) -> str:
    cur = conn.execute(f"SELECT * FROM {table}")
    cols = [description[0] for description in cur.description]
    with open_text_maybe_gzip(path, "wt") as handle:
        writer = csv.writer(handle, delimiter="\t")
        writer.writerow(cols)
        while True:
            rows = cur.fetchmany(100_000)
            if not rows:
                break
            writer.writerows(rows)
    return path


def export_optional_tsvs(conn: sqlite3.Connection, prefix: str) -> List[str]:
    outputs = []
    for table in ("spbc_lookup", "ambiguous_raw_spbc", "observed_pairs", "metadata"):
        path = f"{prefix}.{table}.tsv.gz"
        outputs.append(export_table(conn, table, path))
    return outputs


#----parameters and main


def build_argparser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build a LongAIRR-ready Visium HD 3' SPBC SQLite index "
            "from a Space Ranger possorted_genome_bam.bam."
        )
    )
    parser.add_argument("--version", action="version", version=f"{TOOL_NAME} {TOOL_VERSION}")
    parser.add_argument("--bam", required=True, help="Space Ranger outs/possorted_genome_bam.bam")
    parser.add_argument("--sqlite", "--out", dest="sqlite", required=True, help="Output SQLite index")
    parser.add_argument(
        "--out-prefix",
        default=None,
        help="Output prefix for summary/QC files. Default: SQLite path without .sqlite/.db suffix",
    )
    parser.add_argument("--force", action="store_true", help="Overwrite existing SQLite output")

    parser.add_argument("--samtools", default="samtools", help="samtools executable [default: samtools]")
    parser.add_argument("--threads", type=int, default=8, help="Threads for samtools view [default: 8]")
    parser.add_argument("--max-reads", type=int, default=0, help="Maximum reads to scan; 0 means all [default: 0]")
    parser.add_argument("--progress", type=int, default=1_000_000, help="Progress interval in reads; 0 disables [default: 1000000]")
    parser.add_argument(
        "--chunk-unique",
        type=int,
        default=1_000_000,
        help="Flush after this many unique raw_spbc/spbc_id pairs [default: 1000000]",
    )

    parser.add_argument("--cr-tag", default="CR", help="Raw barcode tag [default: CR]")
    parser.add_argument("--cb-tag", default="CB", help="Corrected barcode tag [default: CB]")

    parser.add_argument(
        "--allowed-lengths",
        type=int,
        nargs="+",
        default=None,
        help="Expected raw CR lengths for summary reporting and optional filtering. Default: report all lengths.",
    )
    parser.add_argument(
        "--filter-lengths",
        action="store_true",
        help="Exclude raw CR lengths outside --allowed-lengths from the index. Default: keep all valid A/C/G/T raw CR lengths.",
    )

    parser.add_argument("--export-tsv", action="store_true", help="Export SQLite tables as gzipped TSV side files")
    return parser


def validate_args(args: argparse.Namespace) -> None:
    if not Path(args.bam).expanduser().exists():
        raise SystemExit(f"Input BAM not found: {args.bam}")
    if args.threads < 1:
        raise SystemExit("--threads must be >= 1")
    if args.max_reads < 0:
        raise SystemExit("--max-reads must be >= 0")
    if args.progress < 0:
        raise SystemExit("--progress must be >= 0")
    if args.chunk_unique < 1:
        raise SystemExit("--chunk-unique must be >= 1")
    if args.allowed_lengths and any(length <= 0 for length in args.allowed_lengths):
        raise SystemExit("--allowed-lengths must contain positive integers")
    if args.filter_lengths and not args.allowed_lengths:
        raise SystemExit("--filter-lengths requires --allowed-lengths")

    samtools_path = args.samtools if os.path.sep in args.samtools else shutil.which(args.samtools)
    if not samtools_path:
        raise SystemExit(
            f"samtools executable not found: {args.samtools}. "
            "Install samtools or provide --samtools /path/to/samtools."
        )


def main() -> None:
    args = build_argparser().parse_args()

    args.bam = os.path.expanduser(args.bam)
    args.sqlite = os.path.expanduser(args.sqlite)
    args.out_prefix = os.path.expanduser(args.out_prefix) if args.out_prefix else default_out_prefix(args.sqlite)

    validate_args(args)

    if args.max_reads == 0:
        args.max_reads = None

    Path(args.out_prefix).parent.mkdir(parents=True, exist_ok=True)

    print("[INFO] Initializing SQLite database...", file=sys.stderr)
    conn = init_db(args.sqlite, force=args.force)

    print("[INFO] Streaming BAM and aggregating raw SPBC -> corrected SPBC evidence...", file=sys.stderr)
    stats, length_read_counts = stream_bam_with_samtools(args, conn)

    print("[INFO] Building lookup tables...", file=sys.stderr)
    build_sequence_centric_tables(conn)
    validate_sqlite_index(conn)

    print("[INFO] Writing summary outputs...", file=sys.stderr)
    summary = collect_summary(conn, args, stats, length_read_counts)
    write_metadata(conn, args, summary)
    summary_path = write_summary_json(args.out_prefix, args, summary)
    qc_path = write_qc_tsv(args.out_prefix, summary)

    exported_paths = export_optional_tsvs(conn, args.out_prefix) if args.export_tsv else []
    conn.close()

    print("[INFO] Done.", file=sys.stderr)
    print(f"SQLite index: {args.sqlite}")
    print(f"Summary: {summary_path}")
    print(f"QC: {qc_path}")
    for path in exported_paths:
        print(f"Exported TSV: {path}")


if __name__ == "__main__":
    main()
