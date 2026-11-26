#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Склейка прайс-листов поставщика (XLSX) в один файл.

Что делает:
- собирает все .xlsx из папки;
- чистит пробелы и пустые строки;
- цены приводит к числу;
- по артикулу оставляет одну строку с минимальной ценой;
- сортирует по цене;
- ведущие нули артикулов не теряются (артикул пишется как текст).

Запуск: python merge_prices.py [папка] [результат.xlsx]
По умолчанию: ./input -> ./merged_prices.xlsx
"""

import sys
from pathlib import Path

import pandas as pd

# По этим подстрокам в заголовках ищем колонку артикула и колонку цены.
ARTICLE_KEYS = ("артикул", "код", "article", "sku", "код товара")
PRICE_KEYS = ("цена", "price", "стоимость")


def find_column(columns, keys):
    """Первый заголовок, содержащий одну из подстрок keys."""
    for col in columns:
        low = str(col).strip().lower()
        if any(k in low for k in keys):
            return col
    return None


def read_one(path: Path) -> pd.DataFrame:
    """Читает один файл и возвращает очищенную таблицу с ценой-числом."""
    # dtype=str: Excel читается без преобразования типов, иначе "00123" станет 123
    df = pd.read_excel(path, dtype=str)
    df.columns = [str(c).strip() for c in df.columns]

    # strip по всем ячейкам; NaN пропускаем как есть
    df = df.map(lambda v: str(v).strip() if v is not None and str(v) != "nan" else v)

    # строки, где все ячейки пустые, выкидываем
    df = df.dropna(how="all")
    df = df[df.astype(str).apply(lambda row: row.str.strip().ne("").any(), axis=1)]

    art_col = find_column(df.columns, ARTICLE_KEYS)
    price_col = find_column(df.columns, PRICE_KEYS)
    if art_col is None or price_col is None:
        raise SystemExit(
            f"{path.name}: не нашёл колонки артикула/цены. "
            f"Колонки файла: {list(df.columns)}"
        )

    # из цены убираем неразрывные пробелы, обычные пробелы, "руб", "₽";
    # запятую меняем на точку — иначе to_numeric не разберёт "1 250,50"
    df[price_col] = (
        df[price_col]
        .astype(str)
        .str.replace("\xa0", "", regex=False)
        .str.replace(" ", "", regex=False)
        .str.replace("руб", "", case=False, regex=False)
        .str.replace("₽", "", regex=False)
        .str.replace(",", ".", regex=False)
    )
    df[price_col] = pd.to_numeric(df[price_col], errors="coerce")

    # строки без цены (текст, мусор) не участвуют
    df = df.dropna(subset=[price_col])
    df["_источник"] = path.name
    return df


def main():
    folder = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("input")
    output = Path(sys.argv[2]) if len(sys.argv) > 2 else Path("merged_prices.xlsx")

    files = sorted(folder.glob("*.xlsx"))
    # чтобы при повторном запуске не читать собственный результат из той же папки
    files = [f for f in files if f.resolve() != output.resolve()]
    if not files:
        raise SystemExit(f"В папке '{folder}' нет XLSX-файлов.")

    parts = [read_one(f) for f in files]
    df = pd.concat(parts, ignore_index=True)

    art_col = find_column(df.columns, ARTICLE_KEYS)
    price_col = find_column(df.columns, PRICE_KEYS)

    # сортируем по цене до drop_duplicates: keep="first" оставит самую дешёвую строку
    df = df.sort_values(price_col).drop_duplicates(subset=[art_col], keep="first")
    df = df.sort_values(price_col, ascending=True, ignore_index=True)

    # артикул и цена — первыми, "_источник" — последней
    cols = [art_col, price_col] + [c for c in df.columns if c not in (art_col, price_col, "_источник")] + ["_источник"]
    df = df[cols]

    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Прайс")
        # формат "@" (текст) на ячейках артикула — чтобы Excel не съел ведущие нули
        ws = writer.sheets["Прайс"]
        art_idx = df.columns.get_loc(art_col) + 1
        for row in range(2, len(df) + 2):
            ws.cell(row=row, column=art_idx).number_format = "@"

    print(f"Файлов обработано: {len(files)}")
    print(f"Строк в результате: {len(df)} (дубликатов удалено: {sum(len(p) for p in parts) - len(df)})")
    print(f"Результат: {output}")


if __name__ == "__main__":
    main()
