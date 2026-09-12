"""Generate a typeable bootstrap credential; never use this for machine tokens."""
import json
from pathlib import Path
import secrets
import sys


def generate(wordlist):
    words = json.loads(Path(wordlist).read_text())
    if (len(words) != 256 or len(set(words)) != 256
            or any(not isinstance(word, str) or not word.isascii()
                   or not word.isalpha() or not word.islower()
                   or not 3 <= len(word) <= 8 for word in words)):
        raise ValueError("Invalid bootstrap word list")
    # Eight independent uniform choices from 256 words provide 64 bits.
    return "-".join(secrets.choice(words) for _ in range(8))


if __name__ == "__main__":
    print(generate(sys.argv[1]))
