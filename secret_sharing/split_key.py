def split_key(key, total, required):
    # Simple simulation (same key distributed)
    shares = [key for _ in range(total)]
    return shares