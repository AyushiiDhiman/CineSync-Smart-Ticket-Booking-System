"""
Small helper so we don't repeat the MySQL connection setup everywhere.
Change the password below to match your local MySQL setup.
"""

import mysql.connector

DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "your_password_here",   # <-- change this before running
    "database": "cinesync"
}


def get_connection():
    # autocommit is off on purpose - we want full control over
    # when a transaction commits, since that's the whole point
    # of the booking + payment flow
    conn = mysql.connector.connect(**DB_CONFIG)
    conn.autocommit = False
    return conn
