import argparse
import csv
import hashlib
import re
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

DATE_FORMATS = ["%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y", "%d/%m/%Y"]
MERCHANT_PREFIXES = [
    "North",
    "River",
    "Maple",
    "Summit",
    "Cedar",
    "Harbor",
    "Aurora",
    "Pine",
    "Lakeside",
    "Stone",
]
MERCHANT_SUFFIXES = [
    "Market",
    "Supply",
    "Cafe",
    "Works",
    "Kitchen",
    "Transit",
    "Store",
    "Foods",
    "Services",
    "Hardware",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Anonymize a private bank CSV into a shareable fixture.")
    parser.add_argument("--csv", required=True, help="Input private CSV path.")
    parser.add_argument("--out", required=True, help="Output anonymized CSV path.")
    parser.add_argument("--shift-days", type=int, default=0, help="Shift all parseable dates by this many days.")
    parser.add_argument("--seed", default="moneyview", help="Stable seed so anonymized output is deterministic.")
    return parser.parse_args()


def is_date_column(name: str) -> bool:
    key = name.lower()
    return "date" in key


def is_amount_column(name: str) -> bool:
    key = name.lower()
    return any(token in key for token in ("amount", "debit", "credit", "balance"))


def is_description_column(name: str) -> bool:
    key = name.lower()
    return any(token in key for token in ("description", "merchant", "payee", "memo", "narrative"))


def is_identifier_column(name: str) -> bool:
    key = name.lower()
    return any(token in key for token in ("account", "routing", "member", "customer", "ssn", "card", "iban"))


def stable_int(seed: str, text: str) -> int:
    digest = hashlib.sha256(f"{seed}|{text}".encode("utf-8")).hexdigest()
    return int(digest[:12], 16)


def anonymize_description(seed: str, original: str) -> str:
    token = re.sub(r"\s+", " ", (original or "").strip())
    if not token:
        return "Merchant Unknown"

    value = stable_int(seed, token)
    prefix = MERCHANT_PREFIXES[value % len(MERCHANT_PREFIXES)]
    suffix = MERCHANT_SUFFIXES[(value // len(MERCHANT_PREFIXES)) % len(MERCHANT_SUFFIXES)]
    code = value % 1000
    return f"{prefix} {suffix} {code:03d}"


def shift_date(raw_value: str, shift_days: int) -> str:
    text = (raw_value or "").strip()
    if not text:
        return text

    for fmt in DATE_FORMATS:
        try:
            parsed = datetime.strptime(text, fmt)
            shifted = parsed + timedelta(days=shift_days)
            return shifted.strftime(fmt)
        except ValueError:
            continue
    return text


def anonymize_amount(seed: str, column: str, raw_value: str) -> str:
    text = (raw_value or "").strip()
    if not text:
        return text

    cleaned = text.replace(",", "").replace("$", "")
    negative_parens = cleaned.startswith("(") and cleaned.endswith(")")
    if negative_parens:
        cleaned = f"-{cleaned[1:-1]}"

    try:
        amount = Decimal(cleaned)
    except InvalidOperation:
        return text

    if amount == 0:
        return text

    variation_bucket = stable_int(seed, f"{column}:{text}") % 11
    variation = Decimal("0.95") + (Decimal(variation_bucket) * Decimal("0.01"))
    adjusted = (amount * variation).quantize(Decimal("0.01"))

    if negative_parens and adjusted < 0:
        return f"({str(abs(adjusted))})"
    return str(adjusted)


def scrub_identifier_text(value: str) -> str:
    text = value or ""
    text = re.sub(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", "redacted@email", text, flags=re.IGNORECASE)
    text = re.sub(r"\b\d{8,}\b", "REDACTED", text)
    text = re.sub(r"\b\d{3}-\d{2}-\d{4}\b", "REDACTED", text)
    return text


def main() -> None:
    args = parse_args()
    input_path = Path(args.csv).expanduser().resolve()
    output_path = Path(args.out).expanduser().resolve()

    if not input_path.exists():
        raise FileNotFoundError(f"Input CSV not found: {input_path}")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with input_path.open("r", encoding="utf-8-sig", newline="") as infile:
        reader = csv.DictReader(infile)
        fieldnames = reader.fieldnames or []

        rows = []
        for row in reader:
            anonymized = {}
            for key, value in row.items():
                current = value or ""

                if is_identifier_column(key):
                    anonymized[key] = "REDACTED"
                    continue

                if is_description_column(key):
                    anonymized[key] = anonymize_description(args.seed, scrub_identifier_text(current))
                    continue

                if is_date_column(key):
                    anonymized[key] = shift_date(current, args.shift_days)
                    continue

                if is_amount_column(key):
                    anonymized[key] = anonymize_amount(args.seed, key, current)
                    continue

                anonymized[key] = scrub_identifier_text(current)

            rows.append(anonymized)

    with output_path.open("w", encoding="utf-8", newline="") as outfile:
        writer = csv.DictWriter(outfile, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"Anonymized fixture written: {output_path}")
    print("Review output before sharing to ensure no identifying text remains.")


if __name__ == "__main__":
    main()
