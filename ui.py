import threading
from tkinter import filedialog, messagebox
import customtkinter as ctk

import gemini_helper as ai
from file_reader import read_file

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

GREEN = "#2e8b57"
RED = "#c0392b"


class StudyApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("AI Study Assistant")
        self.geometry("900x650")
        self.minsize(700, 500)

        # state
        self.cards, self.card_i, self.answer_shown = [], 0, False
        self.quiz, self.quiz_i, self.score, self.answered = [], 0, 0, False
        self.chat_history = []

        self.tabs = ctk.CTkTabview(self)
        self.tabs.pack(fill="both", expand=True, padx=10, pady=10)
        for name in ("Notes", "Summary", "Flashcards", "Quiz", "Chat"):
            self.tabs.add(name)

        self._build_notes()
        self._build_summary()
        self._build_flashcards()
        self._build_quiz()
        self._build_chat()

        self.status = ctk.CTkLabel(self, text="Ready", anchor="w")
        self.status.pack(fill="x", padx=14, pady=(0, 8))

    # ---------- helpers ----------
    def get_notes(self):
        notes = self.notes_box.get("1.0", "end").strip()
        if not notes:
            messagebox.showinfo("No notes", "Paste some notes or upload a file first (Notes tab).")
            self.tabs.set("Notes")
            return None
        return notes

    def run_async(self, func, on_done, busy_text="Working..."):
        """Run func in a thread so the window never freezes, then call on_done(result)."""
        self.status.configure(text=busy_text)

        def worker():
            try:
                result, error = func(), None
            except Exception as e:
                result, error = None, str(e)
            self.after(0, lambda: self._finish(on_done, result, error))

        threading.Thread(target=worker, daemon=True).start()

    def _finish(self, on_done, result, error):
        if error:
            self.status.configure(text="Error")
            messagebox.showerror("Something went wrong", error)
        else:
            self.status.configure(text="Done")
            on_done(result)

    @staticmethod
    def _set_text(box, text):
        box.configure(state="normal")
        box.delete("1.0", "end")
        box.insert("1.0", text)
        box.configure(state="disabled")

    # ---------- Notes ----------
    def _build_notes(self):
        tab = self.tabs.tab("Notes")
        bar = ctk.CTkFrame(tab, fg_color="transparent")
        bar.pack(fill="x", pady=(0, 8))
        ctk.CTkButton(bar, text="Upload PDF / TXT", command=self.upload).pack(side="left")
        ctk.CTkButton(bar, text="Clear", fg_color="gray30", command=lambda: self.notes_box.delete("1.0", "end")).pack(side="left", padx=8)
        self.notes_box = ctk.CTkTextbox(tab, wrap="word")
        self.notes_box.pack(fill="both", expand=True)
        self.notes_box.insert("1.0", "")

    def upload(self):
        path = filedialog.askopenfilename(
            parent=self,
            title="Choose your notes (PDF or TXT)",
            filetypes=[("PDF or text files", ("*.pdf", "*.txt")), ("All files", "*.*")],
        )
        if not path:
            self.status.configure(text="No file selected")
            return
        name = path.replace("\\", "/").split("/")[-1]

        def done(text):
            text = text.strip()
            if not text:
                messagebox.showwarning("Empty file", f"No text could be read from {name}.")
                return
            self.notes_box.delete("1.0", "end")
            self.notes_box.insert("1.0", text)
            self.status.configure(text=f"Loaded {name} ({len(text):,} characters)")

        self.run_async(lambda: read_file(path), done, f"Reading {name}...")

    # ---------- Summary ----------
    def _build_summary(self):
        tab = self.tabs.tab("Summary")
        ctk.CTkButton(tab, text="Summarize", command=self.do_summary).pack(anchor="w", pady=(0, 8))
        self.summary_box = ctk.CTkTextbox(tab, wrap="word", state="disabled")
        self.summary_box.pack(fill="both", expand=True)

    def do_summary(self):
        notes = self.get_notes()
        if notes:
            self.run_async(lambda: ai.summarize(notes), lambda r: self._set_text(self.summary_box, r), "Summarizing...")

    # ---------- Flashcards ----------
    def _build_flashcards(self):
        tab = self.tabs.tab("Flashcards")
        ctk.CTkButton(tab, text="Generate flashcards", command=self.do_cards).pack(anchor="w")
        self.card_count = ctk.CTkLabel(tab, text="")
        self.card_count.pack(pady=(10, 0))
        self.card_label = ctk.CTkLabel(
            tab, text="Click 'Generate flashcards' to start.", wraplength=650,
            font=ctk.CTkFont(size=20), fg_color="gray20", corner_radius=12, height=220,
        )
        self.card_label.pack(fill="x", padx=30, pady=10)
        bar = ctk.CTkFrame(tab, fg_color="transparent")
        bar.pack()
        ctk.CTkButton(bar, text="Previous", width=100, command=lambda: self.move_card(-1)).pack(side="left", padx=5)
        ctk.CTkButton(bar, text="Show answer", width=120, command=self.flip_card).pack(side="left", padx=5)
        ctk.CTkButton(bar, text="Next", width=100, command=lambda: self.move_card(1)).pack(side="left", padx=5)

    def do_cards(self):
        notes = self.get_notes()
        if notes:
            self.run_async(lambda: ai.make_flashcards(notes), self.load_cards, "Making flashcards...")

    def load_cards(self, cards):
        self.cards, self.card_i = cards, 0
        self.show_card()

    def show_card(self):
        if not self.cards:
            return
        self.answer_shown = False
        self.card_count.configure(text=f"Card {self.card_i + 1} of {len(self.cards)}")
        self.card_label.configure(text="Q: " + str(self.cards[self.card_i]["question"]))

    def flip_card(self):
        if not self.cards:
            return
        card = self.cards[self.card_i]
        if self.answer_shown:
            self.show_card()
        else:
            self.answer_shown = True
            self.card_label.configure(text="A: " + str(card["answer"]))

    def move_card(self, step):
        if self.cards:
            self.card_i = (self.card_i + step) % len(self.cards)
            self.show_card()

    # ---------- Quiz ----------
    def _build_quiz(self):
        tab = self.tabs.tab("Quiz")
        ctk.CTkButton(tab, text="Generate quiz", command=self.do_quiz).pack(anchor="w")
        self.q_progress = ctk.CTkLabel(tab, text="")
        self.q_progress.pack(pady=(10, 0))
        self.q_label = ctk.CTkLabel(tab, text="Click 'Generate quiz' to start.", wraplength=700, font=ctk.CTkFont(size=18))
        self.q_label.pack(pady=10)
        self.opt_buttons = []
        for i in range(4):
            b = ctk.CTkButton(tab, text="", height=40, anchor="w", command=lambda i=i: self.pick(i))
            b.pack(fill="x", padx=40, pady=4)
            self.opt_buttons.append(b)
        self.default_color = self.opt_buttons[0].cget("fg_color")
        self.explain = ctk.CTkLabel(tab, text="", wraplength=700, justify="left")
        self.explain.pack(pady=8)
        self.next_btn = ctk.CTkButton(tab, text="Next question", command=self.next_question)
        self.next_btn.pack()
        self.next_btn.pack_forget()

    def do_quiz(self):
        notes = self.get_notes()
        if notes:
            self.run_async(lambda: ai.make_quiz(notes), self.load_quiz, "Making quiz...")

    def load_quiz(self, quiz):
        self.quiz, self.quiz_i, self.score = quiz, 0, 0
        self.show_question()

    def show_question(self):
        q = self.quiz[self.quiz_i]
        self.answered = False
        self.q_progress.configure(text=f"Question {self.quiz_i + 1} of {len(self.quiz)}   |   Score: {self.score}")
        self.q_label.configure(text=q["question"])
        for b, opt in zip(self.opt_buttons, q["options"]):
            b.configure(text=str(opt), fg_color=self.default_color, state="normal")
            b.pack(fill="x", padx=40, pady=4)
        self.explain.configure(text="")
        self.next_btn.pack_forget()

    def pick(self, i):
        if self.answered or not self.quiz:
            return
        self.answered = True
        q = self.quiz[self.quiz_i]
        correct = q["answer_index"]
        if i == correct:
            self.score += 1
            self.opt_buttons[i].configure(fg_color=GREEN)
            verdict = "Correct! "
        else:
            self.opt_buttons[i].configure(fg_color=RED)
            self.opt_buttons[correct].configure(fg_color=GREEN)
            verdict = "Wrong. "
        self.explain.configure(text=verdict + str(q.get("explanation", "")))
        self.q_progress.configure(text=f"Question {self.quiz_i + 1} of {len(self.quiz)}   |   Score: {self.score}")
        last = self.quiz_i == len(self.quiz) - 1
        self.next_btn.configure(text="Finish" if last else "Next question")
        self.next_btn.pack(pady=6)

    def next_question(self):
        if self.quiz_i < len(self.quiz) - 1:
            self.quiz_i += 1
            self.show_question()
        else:
            for b in self.opt_buttons:
                b.pack_forget()
            self.next_btn.pack_forget()
            self.explain.configure(text="")
            self.q_progress.configure(text="")
            self.q_label.configure(text=f"Quiz finished!\nYour score: {self.score} / {len(self.quiz)}")

    # ---------- Chat ----------
    def _build_chat(self):
        tab = self.tabs.tab("Chat")
        self.chat_box = ctk.CTkTextbox(tab, wrap="word", state="disabled")
        self.chat_box.pack(fill="both", expand=True, pady=(0, 8))
        bar = ctk.CTkFrame(tab, fg_color="transparent")
        bar.pack(fill="x")
        self.chat_entry = ctk.CTkEntry(bar, placeholder_text="Ask a question about your notes...")
        self.chat_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.chat_entry.bind("<Return>", lambda e: self.send_chat())
        ctk.CTkButton(bar, text="Send", width=80, command=self.send_chat).pack(side="left")

    def _append_chat(self, who, msg):
        self.chat_box.configure(state="normal")
        self.chat_box.insert("end", f"{who}: {msg}\n\n")
        self.chat_box.see("end")
        self.chat_box.configure(state="disabled")

    def send_chat(self):
        question = self.chat_entry.get().strip()
        if not question:
            return
        notes = self.get_notes()
        if not notes:
            return
        self.chat_entry.delete(0, "end")
        self._append_chat("You", question)
        history = list(self.chat_history)
        self.chat_history.append(("You", question))

        def done(answer):
            self.chat_history.append(("AI", answer))
            self._append_chat("AI", answer)

        self.run_async(lambda: ai.chat(notes, question, history), done, "Thinking...")