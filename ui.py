"""
AI Study Assistant - UI
=======================
A refined dark interface: sidebar navigation, serif headings, gold accents,
and a full Markdown renderer (headings, bold/italic, lists, tables, code
blocks, quotes, links) for everything the AI writes.

Needs:  pip install customtkinter
Uses :  groq_helper.py (or gemini_helper.py as a fallback) and file_reader.py
"""
import queue
import random
import re
import sys
import threading
import tkinter as tk
import webbrowser
from tkinter import filedialog, messagebox

import customtkinter as ctk

try:
    import groq_helper as ai
except ImportError:
    import gemini_helper as ai
from file_reader import read_file

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# --------------------------------------------------------------------------
# Design tokens
# --------------------------------------------------------------------------
BG = "#0d0f14"
SIDEBAR = "#11141b"
SURFACE = "#161a22"
SURFACE_2 = "#1e2430"
BORDER = "#2a3140"
GOLD = "#d4b073"
GOLD_HOVER = "#c29d5e"
GOLD_DIM = "#6b5a3a"
GOLD_SOFT = "#ead9b2"
TEXT = "#ece8df"
MUTED = "#8c93a1"
GREEN = "#58a583"
RED = "#cc6673"
CODE_BG = "#10131a"
ON_GOLD = "#17130a"

if sys.platform.startswith("win"):
    SANS, SERIF, MONO = "Segoe UI", "Georgia", "Consolas"
elif sys.platform == "darwin":
    SANS, SERIF, MONO = "Helvetica Neue", "Georgia", "Menlo"
else:
    SANS, SERIF, MONO = "DejaVu Sans", "DejaVu Serif", "DejaVu Sans Mono"


def cf(size, weight="normal", serif=False, slant="roman"):
    """CustomTkinter font shortcut (must be called after the root window exists)."""
    return ctk.CTkFont(family=SERIF if serif else SANS, size=size, weight=weight, slant=slant)


def plain(text):
    """Strip Markdown markers from short strings (card text, quiz options, table cells)."""
    text = str(text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"(\*\*\*|\*\*|__|~~|`)", "", text)
    text = re.sub(r"(?<![\w*])\*([^*\n]+)\*(?![\w*])", r"\1", text)
    text = re.sub(r"(?<!\w)_([^_\n]+)_(?!\w)", r"\1", text)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    return text.strip()


# --------------------------------------------------------------------------
# Markdown renderer for tk.Text widgets
# --------------------------------------------------------------------------
class Markdown:
    INLINE = re.compile(
        r"(?P<code>`[^`\n]+`)"
        r"|(?P<bi>\*\*\*[^*\n]+\*\*\*)"
        r"|(?P<b>\*\*[^*\n]+\*\*|__[^_\n]+__)"
        r"|(?P<i>(?<![*\w])\*[^*\s][^*\n]*?\*(?!\*)|(?<![_\w])_[^_\s][^_\n]*?_(?![_\w]))"
        r"|(?P<s>~~[^~\n]+~~)"
        r"|(?P<link>\[[^\]\n]+\]\([^)\s]+\))"
    )
    TABLE_SEP = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(?:\|\s*:?-{2,}:?\s*)*\|?\s*$")
    HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$")
    HRULE = re.compile(r"^\s*([-*_])(?:\s*\1){2,}\s*$")
    FENCE = re.compile(r"^\s*```+\s*([\w+#.-]*)\s*$")
    QUOTE = re.compile(r"^\s*>\s?(.*)$")
    BULLET = re.compile(r"^(\s*)[-*+\u2022]\s+(.*)$")
    NUMBER = re.compile(r"^(\s*)(\d{1,3})[.)]\s+(.*)$")

    def __init__(self):
        self._link_count = 0

    # ---- setup -----------------------------------------------------------
    @staticmethod
    def configure(tw):
        """Create every tag the renderer uses on a tk.Text widget."""
        tw.tag_configure("body", font=(SANS, 11), foreground=TEXT, spacing1=3, spacing3=3)
        tw.tag_configure("h1", font=(SERIF, 20, "bold"), foreground=GOLD, spacing1=16, spacing3=6)
        tw.tag_configure("h2", font=(SERIF, 16, "bold"), foreground=GOLD, spacing1=14, spacing3=5)
        tw.tag_configure("h3", font=(SANS, 12, "bold"), foreground=GOLD_SOFT, spacing1=12, spacing3=4)
        tw.tag_configure("quote", font=(SANS, 11, "italic"), foreground=MUTED,
                         lmargin1=14, lmargin2=30, spacing1=3, spacing3=3)
        tw.tag_configure("quotebar", font=(SANS, 11, "bold"), foreground=GOLD)
        tw.tag_configure("hr", font=(SANS, 8), foreground=BORDER, spacing1=8, spacing3=8)
        tw.tag_configure("spacer", font=(SANS, 4))
        tw.tag_configure("bullet", foreground=GOLD)
        for lvl in range(4):
            tw.tag_configure(f"li{lvl}", lmargin1=12 + lvl * 24, lmargin2=34 + lvl * 24)
            tw.tag_configure(f"ol{lvl}", lmargin1=12 + lvl * 24, lmargin2=38 + lvl * 24)
        tw.tag_configure("codelang", font=(SANS, 8, "bold"), foreground=GOLD_DIM, background=CODE_BG,
                         spacing1=4, spacing3=0)
        tw.tag_configure("codeblock", font=(MONO, 10), foreground="#d6dbe5", background=CODE_BG,
                         spacing1=0, spacing3=0)
        tw.tag_configure("placeholder", font=(SANS, 11, "italic"), foreground=MUTED)
        # inline styles last, so they take priority over the block styles
        tw.tag_configure("bold", font=(SANS, 11, "bold"), foreground="#ffffff")
        tw.tag_configure("italic", font=(SANS, 11, "italic"), foreground="#d9d3c5")
        tw.tag_configure("bolditalic", font=(SANS, 11, "bold italic"), foreground="#ffffff")
        tw.tag_configure("strike", overstrike=True, foreground=MUTED)
        tw.tag_configure("code", font=(MONO, 10), foreground="#e8c98e", background=CODE_BG)
        tw.tag_configure("link", foreground="#8ab4f8", underline=True)
        for name in ("bold", "italic", "bolditalic", "strike", "code", "link"):
            tw.tag_raise(name)

    @staticmethod
    def clear(tw):
        """Remove text and destroy any embedded table widgets."""
        for child in list(tw.winfo_children()):
            child.destroy()
        tw.delete("1.0", "end")

    # ---- main entry ------------------------------------------------------
    def render(self, tw, md):
        lines = str(md).replace("\r\n", "\n").replace("\r", "\n").split("\n")
        i, n = 0, len(lines)
        started = False
        gap_pending = False
        indent_stack = []

        while i < n:
            line = lines[i]
            if not line.strip():
                gap_pending = started
                i += 1
                continue
            if gap_pending:
                tw.insert("end", "\n", ("spacer",))
                gap_pending = False
            started = True

            # fenced code block
            fence = self.FENCE.match(line)
            if fence:
                lang = fence.group(1)
                i += 1
                code = []
                while i < n and not lines[i].strip().startswith("```"):
                    code.append(lines[i])
                    i += 1
                i += 1
                self._code_block(tw, code, lang)
                indent_stack = []
                continue

            # table
            if "|" in line and i + 1 < n and self.TABLE_SEP.match(lines[i + 1]):
                header = self._split_row(line)
                aligns = self._aligns(lines[i + 1], len(header))
                rows = []
                j = i + 2
                while j < n and lines[j].strip() and "|" in lines[j]:
                    rows.append(self._split_row(lines[j]))
                    j += 1
                self._table(tw, header, aligns, rows)
                i = j
                indent_stack = []
                continue

            # heading
            m = self.HEADING.match(line)
            if m:
                level = min(len(m.group(1)), 3)
                tw.insert("end", plain(m.group(2)) + "\n", (f"h{level}",))
                i += 1
                indent_stack = []
                continue

            # horizontal rule
            if self.HRULE.match(line):
                tw.insert("end", "\u2500" * 44 + "\n", ("hr",))
                i += 1
                indent_stack = []
                continue

            # block quote
            if self.QUOTE.match(line):
                while i < n and self.QUOTE.match(lines[i]):
                    body = self.QUOTE.match(lines[i]).group(1)
                    tw.insert("end", "\u258e ", ("quote", "quotebar"))
                    self._inline(tw, body, ("quote",))
                    i += 1
                indent_stack = []
                continue

            # lists
            bullet = self.BULLET.match(line)
            number = None if bullet else self.NUMBER.match(line)
            if bullet or number:
                m = bullet or number
                indent = len(m.group(1).expandtabs(4))
                while indent_stack and indent_stack[-1] > indent:
                    indent_stack.pop()
                if not indent_stack or indent_stack[-1] < indent:
                    indent_stack.append(indent)
                level = min(len(indent_stack) - 1, 3)
                if bullet:
                    content = bullet.group(2)
                    content = re.sub(r"^\[ \]\s+", "\u2610 ", content)
                    content = re.sub(r"^\[[xX]\]\s+", "\u2611 ", content)
                    marker = ("\u2022", "\u25e6", "\u25aa", "\u25aa")[level]
                    tw.insert("end", marker + " ", ("bullet", f"li{level}"))
                    self._inline(tw, content, ("body", f"li{level}"))
                else:
                    tw.insert("end", f"{number.group(2)}. ", ("bullet", f"ol{level}"))
                    self._inline(tw, number.group(3), ("body", f"ol{level}"))
                i += 1
                continue

            # plain paragraph line
            indent_stack = []
            self._inline(tw, line.strip(), ("body",))
            i += 1

    # ---- inline ----------------------------------------------------------
    def _inline(self, tw, text, base):
        pos = 0
        for m in self.INLINE.finditer(text):
            if m.start() > pos:
                tw.insert("end", text[pos:m.start()], base)
            kind, tok = m.lastgroup, m.group(0)
            if kind == "code":
                tw.insert("end", tok[1:-1], base + ("code",))
            elif kind == "bi":
                tw.insert("end", tok[3:-3], base + ("bolditalic",))
            elif kind == "b":
                tw.insert("end", tok[2:-2], base + ("bold",))
            elif kind == "i":
                tw.insert("end", tok[1:-1], base + ("italic",))
            elif kind == "s":
                tw.insert("end", tok[2:-2], base + ("strike",))
            elif kind == "link":
                lm = re.match(r"\[(.+?)\]\((.+?)\)", tok)
                self._link(tw, lm.group(1), lm.group(2), base)
            pos = m.end()
        if pos < len(text):
            tw.insert("end", text[pos:], base)
        tw.insert("end", "\n", base)

    def _link(self, tw, label, url, base):
        self._link_count += 1
        tag = f"link_{self._link_count}"
        tw.tag_configure(tag, foreground="#8ab4f8", underline=True)
        tw.tag_bind(tag, "<Button-1>", lambda e, u=url: webbrowser.open(u))
        tw.tag_bind(tag, "<Enter>", lambda e: tw.configure(cursor="hand2"))
        tw.tag_bind(tag, "<Leave>", lambda e: tw.configure(cursor="arrow"))
        tw.insert("end", label, base + ("link", tag))

    # ---- code ------------------------------------------------------------
    def _code_block(self, tw, code, lang):
        if lang:
            tw.insert("end", f"  {lang.upper()}\n", ("codelang",))
        else:
            tw.insert("end", " \n", ("codeblock",))
        for ln in code:
            tw.insert("end", "  " + ln.expandtabs(4) + "\n", ("codeblock",))
        tw.insert("end", " \n", ("codeblock",))

    # ---- tables ----------------------------------------------------------
    @staticmethod
    def _split_row(line):
        s = line.strip()
        if s.startswith("|"):
            s = s[1:]
        if s.endswith("|") and not s.endswith("\\|"):
            s = s[:-1]
        return [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", s)]

    @staticmethod
    def _aligns(sep_line, ncols):
        cells = Markdown._split_row(sep_line)
        out = []
        for c in cells:
            if c.startswith(":") and c.endswith(":"):
                out.append("center")
            elif c.endswith(":"):
                out.append("right")
            else:
                out.append("left")
        return (out + ["left"] * ncols)[:ncols]

    def _table(self, tw, header, aligns, rows):
        ncols = len(header)
        rows = [(r + [""] * ncols)[:ncols] for r in rows]
        avail = tw.winfo_width()
        if avail < 300:
            avail = 760
        wrap = max(90, min(380, (avail - 100) // ncols))

        frame = tk.Frame(tw, bg=BORDER, highlightthickness=0, bd=0)
        last_row = len(rows)
        anchors = {"left": "w", "center": "center", "right": "e"}

        def make_cell(r, c, text, bg, fg, font):
            a = aligns[c]
            lbl = tk.Label(frame, text=plain(text), bg=bg, fg=fg, font=font, wraplength=wrap,
                           justify=a, anchor=anchors[a], padx=12, pady=8, bd=0)
            lbl.grid(row=r, column=c, sticky="nsew",
                     padx=(1, 1 if c == ncols - 1 else 0),
                     pady=(1, 1 if r == last_row else 0))
            self._forward_wheel(lbl, tw)

        for c, h in enumerate(header):
            make_cell(0, c, h, SURFACE_2, GOLD, (SANS, 10, "bold"))
            frame.grid_columnconfigure(c, weight=1)
        for r, row in enumerate(rows, start=1):
            bg = SURFACE if r % 2 else "#1a1f2a"
            for c, cell in enumerate(row):
                make_cell(r, c, cell, bg, TEXT, (SANS, 10))

        self._forward_wheel(frame, tw)
        tw.window_create("end", window=frame, padx=14, pady=8)
        tw.insert("end", "\n", ("body",))

    @staticmethod
    def _forward_wheel(widget, tw):
        """Let the mouse wheel scroll the text even when hovering over a table."""
        def on_wheel(e):
            tw.yview_scroll(-3 if e.delta > 0 else 3, "units")
            return "break"
        widget.bind("<MouseWheel>", on_wheel)
        widget.bind("<Button-4>", lambda e: tw.yview_scroll(-3, "units"))
        widget.bind("<Button-5>", lambda e: tw.yview_scroll(3, "units"))


# --------------------------------------------------------------------------
# Quiz option row
# --------------------------------------------------------------------------
class OptionRow(ctk.CTkFrame):
    STYLES = {
        "normal": (SURFACE, BORDER, TEXT),
        "hover": (SURFACE_2, GOLD_DIM, TEXT),
        "correct": ("#14281f", GREEN, TEXT),
        "wrong": ("#2c171c", RED, TEXT),
        "dim": (SURFACE, BORDER, MUTED),
    }

    def __init__(self, master, letter, command):
        super().__init__(master, fg_color=SURFACE, corner_radius=14, border_width=1, border_color=BORDER)
        self.letter, self.command = letter, command
        self.locked, self.state = False, "normal"
        self.badge = ctk.CTkLabel(self, text=letter, width=34, height=34, corner_radius=17,
                                  fg_color=SURFACE_2, text_color=GOLD, font=cf(13, "bold"))
        self.badge.pack(side="left", padx=(14, 14), pady=11)
        self.text = ctk.CTkLabel(self, text="", anchor="w", justify="left", text_color=TEXT,
                                 font=cf(14), wraplength=620)
        self.text.pack(side="left", fill="x", expand=True, padx=(0, 16), pady=11)
        # Update wraplength when the row resizes
        self.bind("<Configure>", self._on_resize)
        for w in (self, self.badge, self.text):
            w.bind("<Button-1>", self._click)
            w.bind("<Enter>", self._enter)
            w.bind("<Leave>", self._leave)

    def _click(self, _event=None):
        if not self.locked:
            self.command()

    def _on_resize(self, event):
        # Reserve space for badge (34) + padding (14+14+16) = ~78px
        new_wrap = max(200, event.width - 100)
        try:
            self.text._text_label.configure(wraplength=new_wrap)
        except AttributeError:
            try:
                s = self.text._get_widget_scaling()
            except Exception:
                s = 1.0
            self.text.configure(wraplength=int(new_wrap / s))

    def _enter(self, _event=None):
        if not self.locked:
            self.set_state("hover")

    def _leave(self, _event=None):
        if not self.locked:
            self.set_state("normal")

    def set_state(self, state):
        self.state = state
        fg, border, text_color = self.STYLES[state]
        self.configure(fg_color=fg, border_color=border)
        self.text.configure(text_color=text_color)
        if state == "correct":
            self.badge.configure(text="\u2713", fg_color=GREEN, text_color="#0b1a12")
        elif state == "wrong":
            self.badge.configure(text="\u2715", fg_color=RED, text_color="#1f0a0e")
        else:
            self.badge.configure(text=self.letter, fg_color=SURFACE_2, text_color=GOLD)

    def reset(self, text):
        self.locked = False
        self.text.configure(text=text)
        self.set_state("normal")


# --------------------------------------------------------------------------
# Main application
# --------------------------------------------------------------------------
class StudyApp(ctk.CTk):
    PAGES = ("Notes", "Summary", "Flashcards", "Quiz", "Chat")

    def __init__(self):
        super().__init__()
        self.title("AI Study Assistant")
        self.geometry("1180x780")
        self.minsize(960, 660)
        self.configure(fg_color=BG)

        self.md = Markdown()
        self._queue = queue.Queue()
        self.busy = False
        self.current = "Notes"

        # state
        self.summary_raw = ""
        self.cards, self.card_i, self.answer_shown = [], 0, False
        self.quiz, self.quiz_i, self.score, self.answered = [], 0, 0, False
        self.chat_history = []

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._build_sidebar()

        self.content = ctk.CTkFrame(self, fg_color=BG, corner_radius=0)
        self.content.grid(row=0, column=1, sticky="nsew")
        self.pages = {n: ctk.CTkFrame(self.content, fg_color="transparent") for n in self.PAGES}

        self._build_notes()
        self._build_summary()
        self._build_flashcards()
        self._build_quiz()
        self._build_chat()

        self.show_page("Notes")
        self.bind("<Key>", self._on_key)
        for idx, name in enumerate(self.PAGES, start=1):
            self.bind(f"<Control-Key-{idx}>", lambda e, n=name: self.show_page(n))
        self.after(80, self._poll)

    # ======================================================================
    # Shared building blocks
    # ======================================================================
    def _button(self, parent, text, command, kind="primary", width=None):
        kwargs = {"width": width} if width else {}
        if kind == "primary":
            return ctk.CTkButton(parent, text=text, command=command, fg_color=GOLD, hover_color=GOLD_HOVER,
                                 text_color=ON_GOLD, font=cf(13, "bold"), corner_radius=10, height=40, **kwargs)
        return ctk.CTkButton(parent, text=text, command=command, fg_color="transparent", hover_color=SURFACE_2,
                             text_color=TEXT, border_width=1, border_color=BORDER, font=cf(13),
                             corner_radius=10, height=40, **kwargs)

    def _menu(self, parent, values, default):
        menu = ctk.CTkOptionMenu(parent, values=values, width=78, height=36, corner_radius=9,
                                 fg_color=SURFACE, button_color=SURFACE_2, button_hover_color=BORDER,
                                 dropdown_fg_color=SURFACE, dropdown_hover_color=SURFACE_2,
                                 text_color=TEXT, dropdown_text_color=TEXT, font=cf(13), dropdown_font=cf(13))
        menu.set(default)
        return menu

    def _header(self, parent, title, subtitle):
        ctk.CTkLabel(parent, text=title, font=cf(30, "bold", serif=True), text_color=TEXT,
                     anchor="w").pack(anchor="w")
        ctk.CTkLabel(parent, text=subtitle, font=cf(13), text_color=MUTED, anchor="w",
                     justify="left").pack(anchor="w", pady=(4, 0))
        ctk.CTkFrame(parent, height=1, fg_color=BORDER).pack(fill="x", pady=(16, 18))

    def _textbox(self, parent):
        box = ctk.CTkTextbox(parent, fg_color=SURFACE, border_width=1, border_color=BORDER, corner_radius=16,
                             text_color=TEXT, font=(SANS, 11), wrap="word",
                             scrollbar_button_color=BORDER, scrollbar_button_hover_color=MUTED)
        tw = box._textbox
        tw.configure(padx=24, pady=18, insertbackground=GOLD, selectbackground="#4a3f26",
                     selectforeground=TEXT, spacing1=2, spacing3=2)
        Markdown.configure(tw)
        return box

    def _lock(self, box, readonly=True):
        box._textbox.configure(state="disabled" if readonly else "normal")

    def _render(self, box, md_text):
        tw = box._textbox
        tw.configure(state="normal", cursor="arrow")
        Markdown.clear(tw)
        self.md.render(tw, md_text)
        tw.configure(state="disabled")
        tw.yview_moveto(0)

    def _placeholder(self, box, text):
        tw = box._textbox
        tw.configure(state="normal", cursor="arrow")
        Markdown.clear(tw)
        tw.insert("end", text, ("placeholder",))
        tw.configure(state="disabled")

    def _copy(self, text):
        if not text:
            return
        self.clipboard_clear()
        self.clipboard_append(text)
        self._set_status("Copied to clipboard", GREEN)

    # ======================================================================
    # Sidebar, navigation, status
    # ======================================================================
    def _build_sidebar(self):
        side = ctk.CTkFrame(self, width=244, fg_color=SIDEBAR, corner_radius=0)
        side.grid(row=0, column=0, sticky="nsew")
        side.pack_propagate(False)

        brand = ctk.CTkFrame(side, fg_color="transparent")
        brand.pack(fill="x", padx=26, pady=(34, 0))
        ctk.CTkLabel(brand, text="A I   S T U D Y", font=cf(10, "bold"), text_color=GOLD, anchor="w").pack(anchor="w")
        ctk.CTkLabel(brand, text="Assistant", font=cf(28, "bold", serif=True), text_color=TEXT,
                     anchor="w").pack(anchor="w", pady=(2, 0))
        ctk.CTkLabel(brand, text="Learn from your own notes", font=cf(12), text_color=MUTED,
                     anchor="w").pack(anchor="w", pady=(4, 0))
        ctk.CTkFrame(side, height=1, fg_color=BORDER).pack(fill="x", padx=26, pady=(26, 18))

        self.nav = {}
        for idx, name in enumerate(self.PAGES, start=1):
            btn = ctk.CTkButton(side, text=f"0{idx}      {name}", anchor="w", height=46, corner_radius=10,
                                fg_color="transparent", hover_color=SURFACE_2, text_color=TEXT,
                                font=cf(14), command=lambda n=name: self.show_page(n))
            btn.pack(fill="x", padx=16, pady=2)
            self.nav[name] = btn

        footer = ctk.CTkFrame(side, fg_color="transparent")
        footer.pack(side="bottom", fill="x", padx=26, pady=(0, 26))
        model = getattr(ai, "MODEL", "")
        if model:
            ctk.CTkLabel(footer, text=f"MODEL   {model}", font=cf(10), text_color=MUTED, anchor="w").pack(anchor="w", pady=(0, 10))
        self.progress = ctk.CTkProgressBar(footer, height=3, corner_radius=2, progress_color=GOLD,
                                           fg_color=SURFACE_2, mode="determinate")
        self.progress.set(0)
        self.progress.pack(fill="x", pady=(0, 10))
        row = ctk.CTkFrame(footer, fg_color="transparent")
        row.pack(fill="x")
        self.status_dot = ctk.CTkLabel(row, text="\u25cf", font=cf(11), text_color=GREEN, width=14)
        self.status_dot.pack(side="left")
        self.status = ctk.CTkLabel(row, text="Ready", font=cf(12), text_color=MUTED, anchor="w")
        self.status.pack(side="left", padx=(6, 0))

    def show_page(self, name):
        for page in self.pages.values():
            page.pack_forget()
        self.pages[name].pack(fill="both", expand=True, padx=40, pady=(32, 26))
        for n, btn in self.nav.items():
            active = n == name
            btn.configure(fg_color=SURFACE_2 if active else "transparent", text_color=GOLD if active else TEXT)
        self.current = name

    def _set_status(self, text, color=GREEN, busy=False):
        self.status.configure(text=text)
        self.status_dot.configure(text_color=color)
        if busy:
            self.progress.configure(mode="indeterminate")
            self.progress.start()
        else:
            self.progress.stop()
            self.progress.configure(mode="determinate")
            self.progress.set(0)

    # ======================================================================
    # Background work
    # ======================================================================
    def run_async(self, func, on_done, busy_text="Working\u2026", on_error=None):
        """Run func in a thread so the window never freezes, then call on_done(result) on the UI thread."""
        if self.busy:
            self._set_status("Still working, one moment\u2026", GOLD, busy=True)
            return False
        self.busy = True
        self._set_status(busy_text, GOLD, busy=True)

        def worker():
            try:
                out = (on_done, on_error, func(), None)
            except Exception as e:  # shown to the user in the UI
                out = (on_done, on_error, None, str(e) or e.__class__.__name__)
            self._queue.put(out)

        threading.Thread(target=worker, daemon=True).start()
        return True

    def _poll(self):
        try:
            while True:
                on_done, on_error, result, error = self._queue.get_nowait()
                self._finish(on_done, on_error, result, error)
        except queue.Empty:
            pass
        self.after(80, self._poll)

    def _finish(self, on_done, on_error, result, error):
        self.busy = False
        if error:
            self._set_status("Something went wrong", RED)
            if on_error:
                on_error()
            messagebox.showerror("Something went wrong", error)
            return
        self._set_status("Ready", GREEN)
        try:
            on_done(result)
        except Exception as e:
            self._set_status("Something went wrong", RED)
            messagebox.showerror("Something went wrong", str(e))

    def get_notes(self):
        notes = self.notes_box.get("1.0", "end").strip()
        if not notes:
            messagebox.showinfo("No notes yet", "Paste some notes or upload a file first.")
            self.show_page("Notes")
            return None
        return notes

    # ======================================================================
    # Keyboard shortcuts
    # ======================================================================
    def _on_key(self, event):
        focus = self.focus_get()
        if focus is not None and focus.winfo_class() in ("Text", "Entry", "TEntry"):
            return
        key = event.keysym
        if self.current == "Flashcards":
            if key in ("space", "Return"):
                self.flip_card()
            elif key == "Right":
                self.move_card(1)
            elif key == "Left":
                self.move_card(-1)
        elif self.current == "Quiz" and self.quiz:
            if key in ("1", "2", "3", "4"):
                self.pick(int(key) - 1)
            elif key.lower() in ("a", "b", "c", "d"):
                self.pick("abcd".index(key.lower()))
            elif key in ("Return", "Right") and self.answered:
                self.next_question()

    # ======================================================================
    # Notes
    # ======================================================================
    def _build_notes(self):
        page = self.pages["Notes"]
        self._header(page, "Your notes", "Paste study material or import a PDF / TXT file. Every other tab works from here.")
        bar = ctk.CTkFrame(page, fg_color="transparent")
        bar.pack(fill="x", pady=(0, 14))
        self._button(bar, "Upload file", self.upload).pack(side="left")
        self._button(bar, "Clear", self.clear_notes, kind="ghost", width=90).pack(side="left", padx=10)
        self.notes_info = ctk.CTkLabel(bar, text="0 words  \u00b7  0 characters", font=cf(12), text_color=MUTED)
        self.notes_info.pack(side="right")
        self.notes_box = self._textbox(page)
        self.notes_box.pack(fill="both", expand=True)
        self.notes_box.bind("<KeyRelease>", self._update_notes_info)

    def _update_notes_info(self, _event=None):
        text = self.notes_box.get("1.0", "end-1c")
        words, chars = len(text.split()), len(text)
        info = f"{words:,} words  \u00b7  {chars:,} characters"
        limit = getattr(ai, "MAX_CHARS", None)
        over = bool(limit and chars > limit)
        if over:
            info += f"  \u00b7  only the first {limit:,} characters are used"
        self.notes_info.configure(text=info, text_color=GOLD if over else MUTED)

    def clear_notes(self):
        self.notes_box.delete("1.0", "end")
        self._update_notes_info()

    def upload(self):
        path = filedialog.askopenfilename(filetypes=[("Notes", "*.pdf *.txt"), ("All files", "*.*")])
        if not path:
            return

        def done(text):
            self.notes_box.delete("1.0", "end")
            self.notes_box.insert("1.0", text)
            self._update_notes_info()

        self.run_async(lambda: read_file(path), done, "Reading file\u2026")

    # ======================================================================
    # Summary
    # ======================================================================
    def _build_summary(self):
        page = self.pages["Summary"]
        self._header(page, "Smart summary", "The key ideas from your notes, distilled into something quick to review.")
        bar = ctk.CTkFrame(page, fg_color="transparent")
        bar.pack(fill="x", pady=(0, 14))
        self._button(bar, "Generate summary", self.do_summary).pack(side="left")
        self._button(bar, "Copy", lambda: self._copy(self.summary_raw), kind="ghost", width=90).pack(side="left", padx=10)
        self.summary_box = self._textbox(page)
        self.summary_box.pack(fill="both", expand=True)
        self._placeholder(self.summary_box, "Your summary will appear here.")

    def do_summary(self):
        notes = self.get_notes()
        if not notes:
            return

        def done(result):
            self.summary_raw = str(result)
            self._render(self.summary_box, self.summary_raw)

        self.run_async(lambda: ai.summarize(notes), done, "Summarizing\u2026")

    # ======================================================================
    # Flashcards
    # ======================================================================
    def _build_flashcards(self):
        page = self.pages["Flashcards"]
        self._header(page, "Flashcards", "Practise active recall. Try to answer first, then reveal.")
        bar = ctk.CTkFrame(page, fg_color="transparent")
        bar.pack(fill="x")
        self._button(bar, "Generate flashcards", self.do_cards).pack(side="left")
        ctk.CTkLabel(bar, text="Cards", font=cf(12), text_color=MUTED).pack(side="left", padx=(18, 8))
        self.card_n = self._menu(bar, ["5", "8", "10", "15"], "8")
        self.card_n.pack(side="left")
        self._button(bar, "Shuffle", self.shuffle_cards, kind="ghost", width=90).pack(side="right")

        self.card = ctk.CTkFrame(page, fg_color=SURFACE, corner_radius=22, border_width=1, border_color=BORDER)
        self.card.pack(fill="both", expand=True, pady=(18, 14))
        self.card_side = ctk.CTkLabel(self.card, text="", font=cf(11, "bold"), text_color=GOLD)
        self.card_side.pack(pady=(28, 0))
        self.card_text = ctk.CTkLabel(self.card, text="Generate a set to begin.", font=cf(24, serif=True),
                                      text_color=MUTED, justify="center")
        self.card_text.pack(expand=True, fill="x", padx=44)
        self.card_hint = ctk.CTkLabel(self.card, text="", font=cf(11), text_color=MUTED)
        self.card_hint.pack(pady=(0, 24))
        for w in (self.card, self.card_side, self.card_text, self.card_hint):
            w.bind("<Button-1>", lambda e: self.flip_card())
        self.card.bind("<Configure>", self._on_card_resize)

        prog = ctk.CTkFrame(page, fg_color="transparent")
        prog.pack(fill="x", pady=(0, 12))
        self.card_count = ctk.CTkLabel(prog, text="", font=cf(12, "bold"), text_color=GOLD, width=70, anchor="w")
        self.card_count.pack(side="left")
        self.card_bar = ctk.CTkProgressBar(prog, height=4, corner_radius=2, progress_color=GOLD, fg_color=SURFACE_2)
        self.card_bar.set(0)
        self.card_bar.pack(side="left", fill="x", expand=True)

        nav = ctk.CTkFrame(page, fg_color="transparent")
        nav.pack()
        self._button(nav, "\u2190  Previous", lambda: self.move_card(-1), kind="ghost", width=130).pack(side="left", padx=6)
        self.flip_btn = self._button(nav, "Reveal answer", self.flip_card, width=160)
        self.flip_btn.pack(side="left", padx=6)
        self._button(nav, "Next  \u2192", lambda: self.move_card(1), kind="ghost", width=130).pack(side="left", padx=6)

        # Mastery rating buttons (visible after answer is revealed)
        self.mastery_frame = ctk.CTkFrame(page, fg_color="transparent")
        self.mastery_frame.pack(pady=(10, 0))
        self.btn_dont_know = ctk.CTkButton(self.mastery_frame, text="\u2715  Still learning",
                                            command=lambda: self.mark_card("learning"),
                                            fg_color="#2c171c", hover_color="#3d1f27",
                                            text_color=RED, border_width=1, border_color=RED,
                                            font=cf(12, "bold"), corner_radius=10, height=36, width=150)
        self.btn_dont_know.pack(side="left", padx=8)
        self.btn_know = ctk.CTkButton(self.mastery_frame, text="\u2713  Know it",
                                       command=lambda: self.mark_card("know"),
                                       fg_color="#14281f", hover_color="#1c3a2c",
                                       text_color=GREEN, border_width=1, border_color=GREEN,
                                       font=cf(12, "bold"), corner_radius=10, height=36, width=150)
        self.btn_know.pack(side="left", padx=8)
        self.mastery_frame.pack_forget()  # hidden until answer is shown

        # Mastery stats line
        self.mastery_stats = ctk.CTkLabel(page, text="", font=cf(11), text_color=MUTED)
        self.mastery_stats.pack(pady=(6, 0))

    def do_cards(self):
        notes = self.get_notes()
        if not notes:
            return
        n = int(self.card_n.get())
        self.run_async(lambda: ai.make_flashcards(notes, n), self.load_cards, "Making flashcards\u2026")

    def load_cards(self, cards):
        self.cards = [{"question": plain(c["question"]), "answer": plain(c["answer"]), "mastery": None}
                      for c in cards]
        self.card_i = 0
        self.show_card()

    def _set_card_wraplength(self, px):
        """Set wraplength directly on the internal tk.Label to avoid CTk's DPI double-scaling."""
        self._set_wraplength(self.card_text, px)

    @staticmethod
    def _set_wraplength(label, px):
        """Set wraplength on a CTkLabel, bypassing CTk's DPI scaling which double-scales pixel values."""
        try:
            label._text_label.configure(wraplength=px)
        except AttributeError:
            try:
                s = label._get_widget_scaling()
            except Exception:
                s = 1.0
            label.configure(wraplength=int(px / s))

    def _on_card_resize(self, event):
        wrap_w = max(260, event.width - 140)
        self._set_card_wraplength(wrap_w)

    def _draw_card(self, side, text, border, hint, color):
        # Dynamically pick a font size that suits the text length AND the card width
        card_w = self.card.winfo_width()
        if card_w < 10:  # widget not yet mapped
            card_w = 700
        wrap_w = max(260, card_w - 140)
        size = 26 if len(text) < 90 else 20 if len(text) < 220 else 16
        # Shrink further on narrow windows so text always wraps comfortably
        if wrap_w < 400 and size > 18:
            size = 18
        self.card_side.configure(text=side)
        self.card_text.configure(text=text, text_color=color, font=cf(size, serif=True))
        self._set_card_wraplength(wrap_w)
        self.card_hint.configure(text=hint)
        self.card.configure(border_color=border)

    def show_card(self):
        if not self.cards:
            return
        self.answer_shown = False
        c = self.cards[self.card_i]
        self._draw_card("QUESTION", c["question"], BORDER, "Click the card or press Space to reveal the answer", TEXT)
        total = len(self.cards)
        self.card_count.configure(text=f"{self.card_i + 1} / {total}")
        self.card_bar.set((self.card_i + 1) / total)
        self.flip_btn.configure(text="Reveal answer")
        self.mastery_frame.pack_forget()
        self._update_mastery_stats()

    def flip_card(self):
        if not self.cards:
            return
        if self.answer_shown:
            self.show_card()
            return
        self.answer_shown = True
        c = self.cards[self.card_i]
        self._draw_card("ANSWER", c["answer"], GOLD, "Click the card to return to the question", GOLD_SOFT)
        self.flip_btn.configure(text="Show question")
        # Show mastery buttons so the user can rate their recall
        self.mastery_frame.pack(after=self.flip_btn.master, pady=(10, 0))

    def mark_card(self, status):
        """Mark the current card as 'know' or 'learning' and advance."""
        if not self.cards:
            return
        self.cards[self.card_i]["mastery"] = status
        self._update_mastery_stats()
        # Auto-advance to next card
        if self.card_i < len(self.cards) - 1:
            self.move_card(1)
        else:
            self.mastery_frame.pack_forget()

    def _update_mastery_stats(self):
        if not self.cards:
            self.mastery_stats.configure(text="")
            return
        know = sum(1 for c in self.cards if c.get("mastery") == "know")
        learn = sum(1 for c in self.cards if c.get("mastery") == "learning")
        unrated = len(self.cards) - know - learn
        parts = []
        if know:
            parts.append(f"\u2713 {know} known")
        if learn:
            parts.append(f"\u2715 {learn} still learning")
        if unrated and (know or learn):
            parts.append(f"{unrated} unrated")
        self.mastery_stats.configure(text="  \u00b7  ".join(parts))

    def move_card(self, step):
        if self.cards:
            self.card_i = (self.card_i + step) % len(self.cards)
            self.show_card()

    def shuffle_cards(self):
        if self.cards:
            random.shuffle(self.cards)
            self.card_i = 0
            self.show_card()

    # ======================================================================
    # Quiz
    # ======================================================================
    def _build_quiz(self):
        page = self.pages["Quiz"]
        self._header(page, "Knowledge check", "A multiple-choice quiz built from your notes. Keys 1-4 also work.")
        bar = ctk.CTkFrame(page, fg_color="transparent")
        bar.pack(fill="x")
        self._button(bar, "Generate quiz", self.do_quiz).pack(side="left")
        ctk.CTkLabel(bar, text="Questions", font=cf(12), text_color=MUTED).pack(side="left", padx=(18, 8))
        self.quiz_n = self._menu(bar, ["5", "8", "10"], "5")
        self.quiz_n.pack(side="left")

        self.quiz_body = ctk.CTkScrollableFrame(page, fg_color="transparent",
                                                scrollbar_button_color=BORDER, scrollbar_button_hover_color=MUTED)
        self.quiz_body.pack(fill="both", expand=True, pady=(14, 0))
        body = self.quiz_body

        self.quiz_empty = ctk.CTkLabel(body, text="Generate a quiz to begin.\nQuestions are written from your notes.",
                                       font=cf(16, serif=True), text_color=MUTED, justify="center")
        self.q_meta = ctk.CTkLabel(body, text="", font=cf(11, "bold"), text_color=GOLD, anchor="w")
        self.q_bar = ctk.CTkProgressBar(body, height=4, corner_radius=2, progress_color=GOLD, fg_color=SURFACE_2)
        self.q_card = ctk.CTkFrame(body, fg_color=SURFACE, corner_radius=18, border_width=1, border_color=BORDER)
        self.q_text = ctk.CTkLabel(self.q_card, text="", font=cf(21, serif=True), text_color=TEXT,
                                   wraplength=680, justify="left", anchor="w")
        self.q_text.pack(fill="x", padx=28, pady=26)
        self.q_card.bind("<Configure>", lambda e: self._set_wraplength(
            self.q_text, max(260, e.width - 80)))
        self.opts = [OptionRow(body, "ABCD"[i], lambda i=i: self.pick(i)) for i in range(4)]
        self.q_explain_frame = ctk.CTkFrame(body, fg_color=SURFACE, corner_radius=14, border_width=1, border_color=BORDER)
        self.q_explain_title = ctk.CTkLabel(self.q_explain_frame, text="", font=cf(14, "bold"), anchor="w")
        self.q_explain_title.pack(fill="x", padx=20, pady=(14, 2))
        self.q_explain = ctk.CTkLabel(self.q_explain_frame, text="", font=cf(13), text_color=MUTED,
                                      wraplength=640, justify="left", anchor="w")
        self.q_explain.pack(fill="x", padx=20, pady=(0, 14))
        self.q_explain_frame.bind("<Configure>", lambda e: self._set_wraplength(
            self.q_explain, max(260, e.width - 60)))
        self.q_next = self._button(body, "Next question", self.next_question, width=170)

        self.q_result = ctk.CTkFrame(body, fg_color=SURFACE, corner_radius=22, border_width=1, border_color=BORDER)
        self.r_title = ctk.CTkLabel(self.q_result, text="YOUR RESULT", font=cf(11, "bold"), text_color=GOLD)
        self.r_title.pack(pady=(34, 0))
        self.r_pct = ctk.CTkLabel(self.q_result, text="", font=cf(72, "bold", serif=True), text_color=GOLD_SOFT)
        self.r_pct.pack(pady=(6, 0))
        self.r_detail = ctk.CTkLabel(self.q_result, text="", font=cf(16), text_color=TEXT)
        self.r_detail.pack()
        self.r_msg = ctk.CTkLabel(self.q_result, text="", font=cf(14, serif=True, slant="italic"), text_color=MUTED)
        self.r_msg.pack(pady=(8, 20))
        row = ctk.CTkFrame(self.q_result, fg_color="transparent")
        row.pack(pady=(0, 32))
        self._button(row, "Retake this quiz", self.retake_quiz, width=170).pack(side="left", padx=6)
        self._button(row, "New quiz", self.do_quiz, kind="ghost", width=130).pack(side="left", padx=6)

        self._quiz_stage("empty")
        page.bind("<Configure>", self._on_quiz_resize)

    def _on_quiz_resize(self, event):
        wrap = max(260, event.width - 190)
        self._set_wraplength(self.q_text, wrap)
        self._set_wraplength(self.q_explain, wrap)
        for row in self.opts:
            self._set_wraplength(row.text, wrap)

    def _quiz_stage(self, stage):
        for w in (self.quiz_empty, self.q_meta, self.q_bar, self.q_card, *self.opts,
                  self.q_explain_frame, self.q_next, self.q_result):
            w.pack_forget()
        if stage == "empty":
            self.quiz_empty.pack(pady=90)
        elif stage == "question":
            self.q_meta.pack(anchor="w", pady=(2, 0))
            self.q_bar.pack(fill="x", pady=(8, 16))
            self.q_card.pack(fill="x", pady=(0, 14))
            for row in self.opts:
                row.pack(fill="x", pady=5)
        elif stage == "result":
            self.q_result.pack(fill="x", pady=10)

    def do_quiz(self):
        notes = self.get_notes()
        if not notes:
            return
        n = int(self.quiz_n.get())
        self.run_async(lambda: ai.make_quiz(notes, n), self.load_quiz, "Writing quiz\u2026")

    def load_quiz(self, quiz):
        self.quiz = quiz
        self.retake_quiz()

    def retake_quiz(self):
        if not self.quiz:
            return
        self.quiz_i, self.score = 0, 0
        self.show_question()

    def _update_meta(self):
        self.q_meta.configure(text=f"QUESTION {self.quiz_i + 1} OF {len(self.quiz)}        SCORE {self.score}")

    def show_question(self):
        q = self.quiz[self.quiz_i]
        self.answered = False
        self._quiz_stage("question")
        self._update_meta()
        self.q_bar.set((self.quiz_i + 1) / len(self.quiz))
        self.q_text.configure(text=plain(q["question"]))
        for row, option in zip(self.opts, q["options"]):
            row.reset(plain(option))
        self.q_explain_frame.pack_forget()
        self.q_next.pack_forget()

    def pick(self, i):
        if self.answered or not self.quiz or self.current != "Quiz":
            return
        self.answered = True
        q = self.quiz[self.quiz_i]
        correct = q["answer_index"]
        for idx, row in enumerate(self.opts):
            row.locked = True
            row.set_state("correct" if idx == correct else "wrong" if idx == i else "dim")
        ok = i == correct
        if ok:
            self.score += 1
        self._update_meta()
        self.q_explain_title.configure(text="Correct" if ok else "Not quite", text_color=GREEN if ok else RED)
        explanation = plain(q.get("explanation", "")) or f"The correct answer is {'ABCD'[correct]}."
        self.q_explain.configure(text=explanation)
        self.q_explain_frame.pack(fill="x", pady=(10, 8))
        last = self.quiz_i == len(self.quiz) - 1
        self.q_next.configure(text="See results" if last else "Next question")
        self.q_next.pack(anchor="e", pady=(4, 10))

    def next_question(self):
        if self.quiz_i < len(self.quiz) - 1:
            self.quiz_i += 1
            self.show_question()
        else:
            self.finish_quiz()

    def finish_quiz(self):
        total = len(self.quiz)
        pct = round(100 * self.score / total)
        if pct >= 90:
            msg = "Outstanding. You clearly know this material."
        elif pct >= 70:
            msg = "Solid work. A little review will make it stick."
        elif pct >= 50:
            msg = "Getting there. Revisit the areas you missed."
        else:
            msg = "Worth another pass through your notes."
        self._quiz_stage("result")
        self.r_pct.configure(text=f"{pct}%")
        self.r_detail.configure(text=f"{self.score} of {total} correct")
        self.r_msg.configure(text=msg)

    # ======================================================================
    # Chat
    # ======================================================================
    GREETING = ("Ask me anything about the notes you've provided. I'll answer from your material "
                "and tell you when something isn't covered.")
    CHIPS = ("Explain the main idea", "List the key terms", "Give me a real-world example", "What might be on an exam?")

    def _build_chat(self):
        page = self.pages["Chat"]
        top = ctk.CTkFrame(page, fg_color="transparent")
        top.pack(fill="x")
        self._header(top, "Ask your notes", "Answers are grounded in what you've pasted or uploaded.")
        self.chat_box = self._textbox(page)
        self.chat_box.pack(fill="both", expand=True)
        tw = self.chat_tw = self.chat_box._textbox
        tw.tag_configure("speaker_ai", font=(SANS, 9, "bold"), foreground=GOLD, spacing1=8, spacing3=2)
        tw.tag_configure("speaker_you", font=(SANS, 9, "bold"), foreground=MUTED, spacing1=8, spacing3=2)
        tw.tag_configure("user", font=(SANS, 11), foreground=TEXT, background="#1d2331",
                         lmargin1=10, lmargin2=10, rmargin=10, spacing1=5, spacing3=5)
        tw.tag_configure("thinking", font=(SANS, 11, "italic"), foreground=MUTED)
        tw.tag_configure("msgsep", font=(SANS, 8))

        chips = ctk.CTkFrame(page, fg_color="transparent")
        chips.pack(fill="x", pady=(12, 0))
        for label in self.CHIPS:
            ctk.CTkButton(chips, text=label, height=30, corner_radius=15, fg_color="transparent",
                          hover_color=SURFACE_2, border_width=1, border_color=BORDER, text_color=MUTED,
                          font=cf(12), command=lambda t=label: self.send_chat(t)).pack(side="left", padx=(0, 8))
        ctk.CTkButton(chips, text="Clear chat", height=30, corner_radius=15, fg_color="transparent",
                      hover_color=SURFACE_2, text_color=MUTED, font=cf(12), width=90,
                      command=self.clear_chat).pack(side="right")

        bar = ctk.CTkFrame(page, fg_color="transparent")
        bar.pack(fill="x", pady=(10, 0))
        self.chat_entry = ctk.CTkEntry(bar, placeholder_text="Ask a question about your notes\u2026", height=46,
                                       corner_radius=12, fg_color=SURFACE, border_color=BORDER, text_color=TEXT,
                                       placeholder_text_color=MUTED, font=cf(14))
        self.chat_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.chat_entry.bind("<Return>", lambda e: self.send_chat())
        self._button(bar, "Send", self.send_chat, width=100).pack(side="left")
        self._append_chat("AI", self.GREETING)

    def clear_chat(self):
        self.chat_history = []
        tw = self.chat_tw
        tw.configure(state="normal")
        Markdown.clear(tw)
        tw.configure(state="disabled")
        self._append_chat("AI", self.GREETING)

    def _append_chat(self, who, msg):
        tw = self.chat_tw
        tw.configure(state="normal", cursor="arrow")
        if who == "You":
            tw.insert("end", "YOU\n", ("speaker_you",))
            tw.insert("end", str(msg) + "\n", ("user",))
        else:
            tw.insert("end", "ASSISTANT\n", ("speaker_ai",))
            self.md.render(tw, msg)
        tw.insert("end", "\n", ("msgsep",))
        tw.see("end")
        tw.configure(state="disabled")

    def _show_thinking(self):
        tw = self.chat_tw
        tw.configure(state="normal")
        tw.insert("end", "Thinking\u2026\n", ("thinking",))
        tw.see("end")
        tw.configure(state="disabled")

    def _hide_thinking(self):
        tw = self.chat_tw
        ranges = tw.tag_ranges("thinking")
        if ranges:
            tw.configure(state="normal")
            # Delete all ranges in reverse so indices stay valid
            pairs = list(zip(ranges[0::2], ranges[1::2]))
            for start, end in reversed(pairs):
                tw.delete(start, end)
            tw.configure(state="disabled")

    def send_chat(self, text=None):
        question = (text or self.chat_entry.get()).strip()
        if not question:
            return
        notes = self.get_notes()
        if not notes:
            return
        if self.busy:
            self._set_status("Still working, one moment\u2026", GOLD, busy=True)
            return
        self.chat_entry.delete(0, "end")
        self._append_chat("You", question)
        self._show_thinking()
        history = list(self.chat_history)
        self.chat_history.append(("You", question))

        def done(answer):
            self._hide_thinking()
            self.chat_history.append(("AI", answer))
            self._append_chat("AI", answer)

        self.run_async(lambda: ai.chat(notes, question, history), done, "Thinking\u2026", on_error=self._hide_thinking)


if __name__ == "__main__":
    StudyApp().mainloop()
