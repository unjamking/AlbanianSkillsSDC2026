"""Reading the data files. Every file has one record per line, TYPE | field | field, and # starts a comment."""


class DataError(Exception):
    """A data file has problems. errors holds every message, so all of them can be shown at once."""

    def __init__(self, errors):
        super().__init__("\n".join(errors))
        self.errors = errors


def read_records(path):
    """The records of a file as (line number, fields), without the empty lines and the comments."""
    try:
        with open(path, encoding="utf-8-sig") as file:
            lines = [line.strip() for line in file]
    except FileNotFoundError:
        raise DataError([f"File not found: {path}"])
    except UnicodeDecodeError:
        raise DataError([f"Cannot read {path}: it is not a UTF-8 text file."])
    except OSError as error:
        raise DataError([f"Cannot read {path}: {error.strerror}"])
    records = []
    for number, text in enumerate(lines, start=1):
        if text and not text.startswith("#"):
            records.append((number, [field.strip() for field in text.split("|")]))
    return records
