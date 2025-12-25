from pypdf import PdfReader
import re

def _extract_cv_text(pdf_path: str) -> str:
    reader = PdfReader(pdf_path)
    pages = []
    for page in reader.pages:
        text = page.extract_text()
        if text:
            pages.append(text)
    return "\n".join(pages)

def _clean_cv_text(text: str) -> str:
    text = re.sub(r"\n{2,}", "\n", text)     # collapse newlines
    text = re.sub(r"[ \t]+", " ", text)      # normalize spaces
    return text.strip()

def _format_cv_for_llm(cv_text: str) -> str:
    return f"""
Candidate CV (PDF Extract):

{cv_text}

Important:
- Use this CV to ask relevant interview questions.
- Do not quote the CV verbatim unless necessary.
"""

def get_pdf_context(pdf_filepath):
    cv_text = _extract_cv_text(pdf_filepath)
    cv_text = _clean_cv_text(cv_text)
    cv_prompt = _format_cv_for_llm(cv_text)
    return cv_prompt

if __name__ == "__main__":
    print(get_pdf_context('./assets/siboudouki-sample.pdf'))