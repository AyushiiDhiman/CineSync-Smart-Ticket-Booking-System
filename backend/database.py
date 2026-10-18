import mysql.connector

DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "your password here", 
    "database": "cinesync"
}


def get_connection():
    conn = mysql.connector.connect(**DB_CONFIG)
    conn.autocommit = False
    return conn
