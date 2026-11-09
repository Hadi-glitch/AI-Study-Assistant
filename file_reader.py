from pypdf import PdfReader


def read_file(path):
    """Return the text of a .pdf or .txt file."""
    if path.lower().endswith(".pdf"):
        reader = PdfReader(path)
        if reader.is_encrypted:
            try:
                reader.decrypt("")
            except Exception:
                raise ValueError("This PDF is password-protected.")
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        if not text.strip():
            raise ValueError("No text found in this PDF (it may be a scanned image).")
        return text
    for enc in ("utf-8-sig", "utf-16", "cp1252"):
        try:
            with open(path, "r", encoding=enc) as f:
                return f.read()
        except (UnicodeDecodeError, UnicodeError):
            continue
    raise ValueError("Couldn't read this file as text.")


if __name__ == "__main__":
    import sys
    print(read_file(sys.argv[1])[:1000])