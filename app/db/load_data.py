"""
One-time script to load the Olist dataset CSV files into Postgres.
Creates the required tables (if they don't exist) and populates them
from the CSV files stored in the /data folder.
"""

import logging
import pandas as pd
from sqlalchemy import text

from app.db.connection import get_engine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Path inside the container where CSVs live
DATA_DIR = "data"

# Explicit list of columns that must be parsed as real datetime objects
# (Postgres table defines these as TIMESTAMP, so pandas must not leave
# them as plain text strings).
DATE_COLUMNS = {
    "order_purchase_timestamp",
    "order_approved_at",
    "order_delivered_carrier_date",
    "order_delivered_customer_date",
    "order_estimated_delivery_date",
}

# SQL to create all 4 tables with proper relationships
CREATE_TABLES_SQL = """
DROP TABLE IF EXISTS order_items;
DROP TABLE IF EXISTS orders;
DROP TABLE IF EXISTS products;
DROP TABLE IF EXISTS customers;

CREATE TABLE customers (
    customer_id VARCHAR PRIMARY KEY,
    customer_unique_id VARCHAR,
    customer_zip_code_prefix VARCHAR,
    customer_city VARCHAR,
    customer_state VARCHAR
);

CREATE TABLE products (
    product_id VARCHAR PRIMARY KEY,
    product_category_name VARCHAR
);

CREATE TABLE orders (
    order_id VARCHAR PRIMARY KEY,
    customer_id VARCHAR REFERENCES customers(customer_id),
    order_status VARCHAR,
    order_purchase_timestamp TIMESTAMP,
    order_approved_at TIMESTAMP,
    order_delivered_carrier_date TIMESTAMP,
    order_delivered_customer_date TIMESTAMP,
    order_estimated_delivery_date TIMESTAMP
);

CREATE TABLE order_items (
    order_id VARCHAR REFERENCES orders(order_id),
    order_item_id INTEGER,
    product_id VARCHAR REFERENCES products(product_id),
    price NUMERIC,
    freight_value NUMERIC,
    PRIMARY KEY (order_id, order_item_id)
);
"""


def create_tables(engine) -> None:
    """
    Create all required tables in Postgres, dropping them first if they
    already exist (safe to re-run this script during development).

    Args:
        engine: SQLAlchemy engine connected to Postgres.
    """
    try:
        with engine.begin() as conn:
            conn.execute(text(CREATE_TABLES_SQL))
        logger.info("Tables created successfully.")
    except Exception as e:
        logger.error(f"Failed to create tables: {e}")
        raise


def load_csv_to_table(engine, csv_filename: str, table_name: str, columns: list[str]) -> None:
    """
    Load a single CSV file into a Postgres table using pandas.

    Args:
        engine: SQLAlchemy engine connected to Postgres.
        csv_filename (str): Name of the CSV file inside DATA_DIR.
        table_name (str): Target table name in Postgres.
        columns (list[str]): Columns to keep from the CSV (subset).
    """
    filepath = f"{DATA_DIR}/{csv_filename}"
    date_cols_present = [c for c in columns if c in DATE_COLUMNS]
    try:
        df = pd.read_csv(filepath, usecols=columns, parse_dates=date_cols_present)
        df.to_sql(table_name, engine, if_exists="append", index=False)
        logger.info(f"Loaded {len(df)} rows into '{table_name}' from {csv_filename}.")
    except FileNotFoundError:
        logger.error(f"CSV file not found: {filepath}")
        raise
    except Exception as e:
        logger.error(f"Failed to load {csv_filename} into {table_name}: {e}")
        raise


def main() -> None:
    """
    Entry point: creates tables and loads all 4 CSV files into Postgres,
    in the correct order to respect foreign key constraints
    (customers/products first, then orders, then order_items).
    """
    engine = get_engine()
    create_tables(engine)

    load_csv_to_table(
        engine,
        "olist_customers_dataset.csv",
        "customers",
        ["customer_id", "customer_unique_id", "customer_zip_code_prefix", "customer_city", "customer_state"],
    )
    load_csv_to_table(
        engine,
        "olist_products_dataset.csv",
        "products",
        ["product_id", "product_category_name"],
    )
    load_csv_to_table(
        engine,
        "olist_orders_dataset.csv",
        "orders",
        [
            "order_id", "customer_id", "order_status",
            "order_purchase_timestamp", "order_approved_at",
            "order_delivered_carrier_date", "order_delivered_customer_date",
            "order_estimated_delivery_date",
        ],
    )
    load_csv_to_table(
        engine,
        "olist_order_items_dataset.csv",
        "order_items",
        ["order_id", "order_item_id", "product_id", "price", "freight_value"],
    )

    logger.info("All data loaded successfully.")


if __name__ == "__main__":
    main()