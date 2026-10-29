from __future__ import annotations

import argparse
import sys

from app.database import close_database
from app.services.dataset import extend_dataset_history, seed_all
from app.utils import format_dt


def main() -> int:
    parser = argparse.ArgumentParser(description="Muat dataset sensor CMMS Sentinel ke MongoDB.")
    parser.add_argument("--reset", action="store_true", help="Hapus seluruh koleksi aplikasi sebelum seeding.")
    parser.add_argument("--yes", action="store_true", help="Konfirmasi otomatis untuk --reset.")
    parser.add_argument(
        "--extend-history",
        action="store_true",
        help="Tambahkan riwayat sintetis lama tanpa menghapus atau menimpa data yang ada.",
    )
    args = parser.parse_args()
    if args.reset and args.extend_history:
        parser.error("--reset dan --extend-history tidak dapat digunakan bersamaan.")
    if args.reset and not args.yes:
        answer = input("Semua data aplikasi pada database akan dihapus. Ketik 'reset' untuk melanjutkan: ")
        if answer.strip().lower() != "reset":
            print("Dibatalkan.")
            return 1
    try:
        summary = extend_dataset_history() if args.extend_history else seed_all(reset=args.reset)
    finally:
        close_database()
    if args.extend_history:
        print("Perluasan riwayat dataset selesai tanpa reset database.")
        print(f"Pembacaan ditambahkan : {summary['readings_added']:,}")
        print(f"CSV sensor            : {summary['csv_readings']:,} baris")
        print(f"Periode sintetis      : {format_dt(summary['dataset_start'])} s.d. {format_dt(summary['dataset_end'])} WIB")
        print(f"Mesin sumber langsung dilewati : {', '.join(summary['skipped_real_machines']) or 'tidak ada'}")
        print(f"Mesin tidak ditemukan         : {', '.join(summary['skipped_missing_machines']) or 'tidak ada'}")
        print(f"CSV dataset           : {summary['dataset']}")
        return 0
    if not summary.get("seeded"):
        print(f"Seeder dilewati: {summary.get('reason')}")
        print(f"Mesin: {summary.get('machines')} · Pembacaan: {summary.get('readings'):,}")
        return 0
    print("Dataset berhasil dimuat.")
    print(f"Mesin         : {summary['machines']}")
    print(f"Pembacaan     : {summary['readings']:,}")
    print(f"Alert         : {summary['alerts']}")
    print(f"Work order    : {summary['work_orders']}")
    print(f"Periode data  : {format_dt(summary['first'])} s.d. {format_dt(summary['last'])} WIB")
    print(f"CSV dataset   : {summary['dataset']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
