import socket
import threading
import time
import argparse
import os
from resp_parser import RESPParser

def parse_args():
    parser = argparse.ArgumentParser(description="Redis RDB Persistence Extension")
    parser.add_argument('--dir', required=False, help='指定儲存 RDB 檔案的目錄，例如 /tmp/redis-files')
    parser.add_argument('--dbfilename', required=False, help='指定 RDB 檔案的檔名，例如 dump.rdb')
    return parser.parse_args()

storage = {}
dir = "/tmp/redis-files"
dbfilename = "dump.rpb"


def read_length(f, first_byte=None):
    if first_byte is None:
        first_byte = f.read(1)
        if not first_byte:
            raise Exception("Unexpected EOF reading length")
        b = first_byte[0]
    else:
        b = first_byte if isinstance(first_byte, int) else first_byte[0]
    mode = b & 0xC0
    if mode == 0x00:
        return b & 0x3F
    elif mode == 0x40:
        second = f.read(1)
        if not second:
            raise Exception("Unexpected EOF reading 14-bit length")
        return ((b & 0x3F) << 8) | second[0]
    elif mode == 0x80:
        rest = f.read(4)
        if len(rest) < 4:
            raise Exception("Unexpected EOF reading 32-bit length")
        return int.from_bytes(rest, byteorder='big')
    elif mode == 0xC0:
        # Special encoding not supported in this stage
        return None

def read_string(f):
    first_byte = f.read(1)
    if not first_byte:
        raise Exception("Unexpected EOF reading string")
    b = first_byte[0]
    mode = b & 0xC0
    if mode != 0xC0:
        if mode == 0x00:
            length = b & 0x3F
        elif mode == 0x40:
            second = f.read(1)
            if not second:
                raise Exception("Unexpected EOF reading 14-bit string length")
            length = ((b & 0x3F) << 8) | second[0]
        elif mode == 0x80:
            rest = f.read(4)
            if len(rest) < 4:
                raise Exception("Unexpected EOF reading 32-bit string length")
            length = int.from_bytes(rest, byteorder='big')
        else:
            raise Exception("Unknown mode in read_string")
        data = f.read(length)
        if len(data) < length:
            raise Exception("Unexpected EOF reading string data")
        return data.decode('utf-8', errors='replace')
    else:
        raise Exception("Special encoding not supported in this stage")

def safe_skip_string(f):
    first_byte = f.read(1)
    if not first_byte:
        raise Exception("Unexpected EOF in safe_skip_string")
    b = first_byte[0]
    mode = b & 0xC0
    if mode != 0xC0:
        if mode == 0x00:
            length = b & 0x3F
        elif mode == 0x40:
            second = f.read(1)
            if not second:
                raise Exception("Unexpected EOF in safe_skip_string (14-bit)")
            length = ((b & 0x3F) << 8) | second[0]
        elif mode == 0x80:
            rest = f.read(4)
            if len(rest) < 4:
                raise Exception("Unexpected EOF in safe_skip_string (32-bit)")
            length = int.from_bytes(rest, byteorder='big')
        f.read(length)
    else:
        encoding_type = b & 0x3F
        if encoding_type == 0:
            f.read(1)
        elif encoding_type == 1:
            f.read(2)
        elif encoding_type == 2:
            f.read(4)
        else:
            raise Exception("Unsupported special encoding in safe_skip_string")

def read_keys_from_rdb(filepath):
    keys = []
    try:
        with open(filepath, "rb") as f:
            header = f.read(9)
            if header != b"REDIS0011":
                return []
            # Skip metadata sections if present
            while True:
                pos = f.tell()
                marker = f.read(1)
                if not marker:
                    break
                if marker[0] == 0xFA:
                    safe_skip_string(f)
                    safe_skip_string(f)
                else:
                    f.seek(pos)
                    break
            # Check for database section marker FE
            marker = f.read(1)
            if marker and marker[0] == 0xFE:
                _ = read_length(f)  # DB index
            else:
                if marker:
                    f.seek(-1, os.SEEK_CUR)
            # Expect FB marker indicating key-value hash table info
            marker = f.read(1)
            if not marker or marker[0] != 0xFB:
                return []
            total_keys = read_length(f)
            _ = read_length(f)  # expire count (ignored)
            for i in range(total_keys):
                # Read optional expiry marker and value type
                b = f.read(1)
                if not b:
                    break
                if b[0] in (0xFC, 0xFD):
                    if b[0] == 0xFC:
                        f.read(8)
                    else:
                        f.read(4)
                    vt = f.read(1)
                else:
                    vt = b
                key = read_string(f)
                _ = read_string(f)  # skip value
                keys.append(key)
            return keys
    except Exception:
        return []

def read_rdb_value(filepath, target_key):
    try:
        with open(filepath, "rb") as f:
            header = f.read(9)
            if header != b"REDIS0011":
                return None
            # Skip metadata sections if present
            while True:
                pos = f.tell()
                marker = f.read(1)
                if not marker:
                    break
                if marker[0] == 0xFA:
                    safe_skip_string(f)
                    safe_skip_string(f)
                else:
                    f.seek(pos)
                    break
            # Check for database section marker FE
            marker = f.read(1)
            if marker and marker[0] == 0xFE:
                _ = read_length(f)  # DB index
            else:
                if marker:
                    f.seek(-1, os.SEEK_CUR)
            # Expect FB marker indicating key-value hash table info
            marker = f.read(1)
            if not marker or marker[0] != 0xFB:
                return None
            total_keys = read_length(f)
            _ = read_length(f)  # expire count (ignored)
            for i in range(total_keys):
                expire_time = None
                b = f.read(1)
                if not b:
                    break
                if b[0] in (0xFC, 0xFD):
                    if b[0] == 0xFC:
                        expire_bytes = f.read(8)
                        expire_time = int.from_bytes(expire_bytes, byteorder='little')
                        current_time = int(time.time()*1000)
                    else:
                        expire_bytes = f.read(4)
                        expire_time = int.from_bytes(expire_bytes, byteorder='little')
                        current_time = int(time.time())
                    vt = f.read(1)
                else:
                    vt = b
                key = read_string(f)
                value = read_string(f)
                if key == target_key:
                    if expire_time is not None and expire_time < current_time:
                        return None
                    return value
            return None
    except Exception:
        return None

def handle_echo(connection, parsed):
    if len(parsed) < 2:
        connection.sendall(b"-Error: wrong number of arguments for ECHO\r\n")
        return
    message = parsed[1]
    connection.sendall(f"+{message}\r\n".encode())

def handle_ping(connection, parsed):
    connection.sendall(b"+PONG\r\n")

def handle_set(connection, parsed):
    if len(parsed) < 3:
        connection.sendall(b"-Error: wrong number of arguments for SET\r\n")
        return
    key = parsed[1]
    value = parsed[2]
    global storage
    if len(parsed) == 5:
        if parsed[3].upper() == "PX":
            expire_time = int(parsed[4])
            current_time = int(time.time() * 1000)
            expire_time += current_time
            storage[key] = (value, expire_time)
    else:
        storage[key] = (value, -1)
    connection.sendall(b"+OK\r\n")

def handle_get(connection, parsed):
    if len(parsed) != 2:
        connection.sendall(b"-Error: wrong number of arguments for GET\r\n")
        return
    key = parsed[1]
    global storage
    current_time = int(time.time() * 1000)
    if key in storage:
        if storage[key][1] != -1 and storage[key][1] < current_time:
            del storage[key]
        else:
            value = storage[key][0]
            connection.sendall(f"${len(value)}\r\n{value}\r\n".encode())
            return
    if dir is None or dbfilename is None:
        connection.sendall(b"$-1\r\n")
        return
    filepath = os.path.join(dir, dbfilename)
    if not os.path.exists(filepath):
        connection.sendall(b"$-1\r\n")
        return
    value = read_rdb_value(filepath, key)
    if value is None:
        connection.sendall(b"$-1\r\n")
        return
    connection.sendall(f"${len(value)}\r\n{value}\r\n".encode())

def handle_config_branch(connection, parsed):
    if len(parsed) == 3 and parsed[1].upper() == "GET":
        param = parsed[2].lower()
        if param == "dir":
            key = "dir"
            value = dir if dir is not None else ""
        elif param == "dbfilename":
            key = "dbfilename"
            value = dbfilename if dbfilename is not None else ""
        else:
            connection.sendall(b"*0\r\n")
            return
        response = f"*2\r\n${len(key)}\r\n{key}\r\n${len(value)}\r\n{value}\r\n"
        connection.sendall(response.encode())
    else:
        connection.sendall(b"-Error: unsupported CONFIG command\r\n")

def handle_keys(connection, parsed):
    if len(parsed) != 2:
        connection.sendall(b"-Error: wrong number of arguments for KEYS\r\n")
        return
    pattern = parsed[1]
    if pattern != "*":
        connection.sendall(b"-Error: only '*' pattern is supported\r\n")
        return
    if dir is None or dbfilename is None:
        keys = []
    else:
        filepath = os.path.join(dir, dbfilename)
        if not os.path.exists(filepath):
            keys = []
        else:
            keys = read_keys_from_rdb(filepath)
    response = f"*{len(keys)}\r\n"
    for key in keys:
        response += f"${len(key)}\r\n{key}\r\n"
    connection.sendall(response.encode())

command_handlers = {
    "ECHO": handle_echo,
    "PING": handle_ping,
    "SET": handle_set,
    "GET": handle_get,
    "CONFIG": handle_config_branch,
    "KEYS": handle_keys,
}

def expired_key_checker():
    while True:
        global storage
        current_time = int(time.time() * 1000)
        keys_to_delete = []
        for key, value in storage.items():
            if value[1] != -1 and value[1] < current_time:
                keys_to_delete.append(key)
        for key in keys_to_delete:
            del storage[key]
        time.sleep(0.1)

def client_handler(connection, addr):
    while True:
        data = connection.recv(1024).decode()
        if not data:
            break
        parser = RESPParser(data)
        parsed = parser.parse()
        if not parsed:
            connection.sendall(b"-Error: invalid command format\r\n")
            continue
        command = parsed[0].upper()
        if command in command_handlers:
            command_handlers[command](connection, parsed)
        else:
            connection.sendall(b"-Error: unknown command\r\n")
    connection.close()

def init_args(args):
    global dir, dbfilename
    dir = args.dir
    dbfilename = args.dbfilename

def main():
    args = parse_args()
    init_args(args)
    print("Logs from your program will appear here!")
    server_socket = socket.create_server(("localhost", 6379), reuse_port=True)
    while True:
        connection, addr = server_socket.accept()
        client_thread = threading.Thread(target=client_handler, args=(connection, addr))
        client_thread.start()

if __name__ == "__main__":
    main()

