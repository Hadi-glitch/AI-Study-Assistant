from pypdf import PdfReader


def read_file(path):
    """Return the text of a .pdf or .txt file."""
    if path.lower().endswith(".pdf"):
        reader = PdfReader(path)
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        if not text.strip():
            raise ValueError("No text found in this PDF (it may be a scanned image).")
        return text
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()


if __name__ == "__main__":
    import sys
    print(read_file(sys.argv[1])[:1000])
