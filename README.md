# Simple Redis-like Server in Python

This project is a basic implementation of a Redis-like server in Python.  It's designed to handle a subset of Redis commands and provides a rudimentary form of persistence by reading from an RDB (Redis Database) file on startup.  It **does not** write to the RDB file; all changes are stored in memory only.

## Supported Commands

The server supports the following commands:

-   `PING`: Responds with "PONG".  A simple liveness check.
-   `ECHO <message>`: Returns the provided `<message>`.
-   `SET <key> <value> [PX <milliseconds>]`: Sets a key-value pair in the in-memory store.
    -   `PX <milliseconds>`:  (Optional) Sets an expiration time for the key, in milliseconds.
-   `GET <key>`: Retrieves the value associated with the given `<key>`.
    -   Returns the value as a bulk string.
    -   Returns `$-1\r\n` (nil) if the key doesn't exist or has expired.  This check is done against both the in-memory store and the RDB file.
-   `CONFIG GET <parameter>`: Retrieves configuration settings.  Currently supports:
    -   `CONFIG GET dir`: Returns the directory used for RDB file loading.
    -   `CONFIG GET dbfilename`: Returns the filename of the RDB file.
-   `KEYS *`:  Lists all keys found in the *RDB file*.  This command **only** reads from the RDB file; it does *not* reflect keys that have been set only in memory. Supports only the `*` wildcard.

## Running the Server

1.  **Prerequisites:** Python 3.8 or later is required.
2.  **Start the Server:**  Run the `main.py` script directly.  You can optionally specify the directory and filename for the RDB file:

    ```bash
    python3 main.py  # Uses default: /tmp/redis-files/dump.rdb
    python3 main.py --dir /path/to/data --dbfilename mydata.rdb
    ```

3.  **Interact with the Server:** Use a Redis client like `redis-cli` to connect (default port 6379):

    ```bash
    redis-cli PING
    redis-cli ECHO "Hello from my server!"
    redis-cli SET mykey myvalue
    redis-cli GET mykey
    redis-cli SET expiring_key somevalue PX 2000  # Expires in 2 seconds
    redis-cli GET expiring_key
    redis-cli CONFIG GET dir
    redis-cli CONFIG GET dbfilename
    redis-cli KEYS *
    ```

## Basic RDB Persistence (Read-Only)

The server implements a *read-only* form of persistence.  On startup, it attempts to load data from an RDB file (specified by `--dir` and `--dbfilename`).  This RDB file must adhere to a very specific, limited subset of the full RDB specification:

-   **Version:**  The RDB file *must* start with the magic string `REDIS0011`.
-   **Data Types:** Only string key-value pairs are supported.  Hashes, lists, sets, etc., are *not* handled.
-   **Encoding:** The server only handles basic string encoding.  It does *not* support LZF compression or integer encodings.
-   **Structure:**  The RDB file is expected to have the following structure (simplified):
    -   `REDIS0011` (header)
    -   Optional metadata sections (skipped)
    -   `0xFE` (database selector, ignored)
    -   `0xFB` (hash table marker)
        -   Number of keys (length-encoded)
        -   Number of expires (length-encoded, ignored)
        -   Key-value pairs:
            -   Optional expiry time marker (`0xFC` for milliseconds, `0xFD` for seconds) followed by the expiry timestamp.
            -   Value type byte. (Only string type (value 0) is fully supported if no expiry marker exist).
            -   Key (length-encoded string)
            -   Value (length-encoded string)
    -  End of file.

The `read_rdb_value` and `read_keys_from_rdb` functions in `main.py` implement this limited RDB parsing.

**Important:**  The server *never* writes to the RDB file.  All `SET` operations are only applied to the in-memory `storage` dictionary.

## In-Memory Storage

The `storage` dictionary in `main.py` is the primary data store:

```python
storage = {}  # { key: (value, expiry_timestamp) }
```

-   `key`:  The key (string).
-   `value`: The value (string).
-   `expiry_timestamp`:  The expiration time as a Unix timestamp (milliseconds).  A value of `-1` indicates no expiration.

The `expired_key_checker` function runs in a separate thread and removes expired keys from this dictionary.

## Limitations and Notes

-   **No RDB Writing:** This is a read-only implementation.  The server will not persist changes to disk.
-   **Limited RDB Support:**  Only a tiny subset of the RDB format is supported.
-   **Concurrency:**  The server is multi-threaded, but it's not optimized for high concurrency or performance.
-   **Error Handling:** Error handling is basic.  More robust error checking and reporting would be needed for a production system.
-   **Security:**  This server is *not* secure and should not be used in any environment where security is a concern.
- **Encoding**: The read_string function will raise the error if the mode is 0xC0.
-   **RESP Parsing:** The `RESPParser` class handles basic RESP arrays and bulk strings, but it's not a complete RESP implementation.
