"""
deadlock_demo.py

Standalone script for the viva/demo - NOT part of the main app.
Creates a real deadlock on purpose and shows MySQL's InnoDB engine
detecting and breaking it automatically.

Setup:
    Txn A locks seat 1, then tries to lock seat 2
    Txn B locks seat 2, then tries to lock seat 1
    -> circular wait -> InnoDB detects it and kills one transaction

Run with: python deadlock_demo.py
(reset seat 1 and seat 2 to 'available' in the DB before running,
otherwise the FOR UPDATE locks below won't behave the same way)
"""

import threading
import time

from database import get_connection


def transaction_a():
    conn = get_connection()
    cursor = conn.cursor()
    try:
        print("[Txn A] locking seat 1...")
        cursor.execute("SELECT * FROM seats WHERE id = 1 FOR UPDATE")
        print("[Txn A] got seat 1. waiting 2s before asking for seat 2...")
        time.sleep(2)

        print("[Txn A] now trying to lock seat 2...")
        cursor.execute("SELECT * FROM seats WHERE id = 2 FOR UPDATE")
        print("[Txn A] got seat 2 too - committing")
        conn.commit()

    except Exception as e:
        print(f"[Txn A] ABORTED by MySQL: {e}")
        conn.rollback()
    finally:
        cursor.close()
        conn.close()


def transaction_b():
    conn = get_connection()
    cursor = conn.cursor()
    try:
        print("[Txn B] locking seat 2...")
        cursor.execute("SELECT * FROM seats WHERE id = 2 FOR UPDATE")
        print("[Txn B] got seat 2. waiting 2s before asking for seat 1...")
        time.sleep(2)

        print("[Txn B] now trying to lock seat 1...")
        cursor.execute("SELECT * FROM seats WHERE id = 1 FOR UPDATE")
        print("[Txn B] got seat 1 too - committing")
        conn.commit()

    except Exception as e:
        print(f"[Txn B] ABORTED by MySQL: {e}")
        conn.rollback()
    finally:
        cursor.close()
        conn.close()


if __name__ == "__main__":
    print("Starting deadlock demo")
    print("Txn A will lock seat1 -> seat2")
    print("Txn B will lock seat2 -> seat1")
    print("This is a classic circular wait - MySQL should detect it")
    print("and kill one of the two transactions automatically.\n")

    t1 = threading.Thread(target=transaction_a)
    t2 = threading.Thread(target=transaction_b)

    t1.start()
    t2.start()
    t1.join()
    t2.join()

    print("\nDone. One transaction should have committed successfully,")
    print("the other should show something like:")
    print("'Deadlock found when trying to get lock; try restarting transaction'")
    print("That error message IS the deadlock detection working.")
    print("\nNote: our group-booking code (hold-group endpoint) actually AVOIDS")
    print("this problem on purpose, by always locking seats in sorted ID order -")
    print("that consistent ordering is a classic deadlock-prevention technique.")
    print("This script skips that safeguard deliberately, so we have something")
    print("to demonstrate deadlock DETECTION with.")
