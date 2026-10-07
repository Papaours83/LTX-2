"""Petite interface graphique pour creer des videos avec LTX-2 (DistilledPipeline)."""

import os
import random
import subprocess
import sys
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk

from PIL import Image, ImageTk

ROOT = Path(__file__).resolve().parent
MODELS = ROOT / "models" / "ltx-2.5"
OUTPUTS = ROOT / "outputs"
PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"

FORMATS = {
    "Paysage (768 x 512)": (768, 512),
    "Portrait (512 x 768)": (512, 768),
    "Carre (640 x 640)": (640, 640),
}

EXEMPLE = (
    "A golden retriever runs joyfully across a sunny beach, waves crashing softly behind it, "
    "its ears flapping in the wind. The camera tracks it from the side at a low angle. "
    "Warm late-afternoon sunlight. The sound of waves and happy barking."
)


def taille_fichier_echange_go() -> float:
    """Taille max du fichier d'echange Windows en Go (0 si inconnue)."""
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "(Get-CimInstance Win32_PageFileUsage | Measure-Object AllocatedBaseSize -Sum).Sum"],
            capture_output=True, text=True, timeout=20, creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return int(out.stdout.strip() or 0) / 1024
    except Exception:
        return 0


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("LTX-2 - Creer une video")
        self.geometry("760x800")
        self.minsize(600, 560)
        self.process: subprocess.Popen | None = None
        self.derniere_video: Path | None = None

        pad = {"padx": 12, "pady": 4}

        ttk.Label(self, text="Decris ta video (en anglais) :", font=("Segoe UI", 11, "bold")).pack(anchor="w", **pad)
        self.prompt = tk.Text(self, height=7, wrap="word", font=("Segoe UI", 10))
        self.prompt.pack(fill="x", **pad)
        self.prompt.insert("1.0", EXEMPLE)

        cadre_image = ttk.LabelFrame(self, text="Image de depart (facultatif) : la video commencera par cette image")
        cadre_image.pack(fill="x", **pad)
        self.image: Path | None = None
        self.apercu = ttk.Label(cadre_image, text="Aucune image", width=22, anchor="center")
        self.apercu.pack(side="left", padx=8, pady=6)
        ttk.Button(cadre_image, text="Choisir une image...", command=self.choisir_image).pack(side="left", padx=4)
        self.btn_retirer = ttk.Button(cadre_image, text="Retirer", command=self.retirer_image, state="disabled")
        self.btn_retirer.pack(side="left", padx=4)

        reglages = ttk.Frame(self)
        reglages.pack(fill="x", **pad)

        ttk.Label(reglages, text="Duree :").grid(row=0, column=0, sticky="w")
        self.duree = tk.DoubleVar(value=2)
        self.duree_label = ttk.Label(reglages, text="2 s", width=5)
        ttk.Scale(reglages, from_=1, to=5, variable=self.duree, length=180,
                  command=lambda v: self.duree_label.config(text=f"{round(float(v))} s")).grid(row=0, column=1, sticky="w")
        self.duree_label.grid(row=0, column=2, sticky="w", padx=(4, 24))

        ttk.Label(reglages, text="Format :").grid(row=0, column=3, sticky="w")
        self.format = tk.StringVar(value=next(iter(FORMATS)))
        ttk.Combobox(reglages, textvariable=self.format, values=list(FORMATS), state="readonly", width=20).grid(
            row=0, column=4, sticky="w")

        ttk.Label(reglages, text="Seed :").grid(row=1, column=0, sticky="w", pady=(8, 0))
        self.seed = tk.StringVar(value="")
        ttk.Entry(reglages, textvariable=self.seed, width=12).grid(row=1, column=1, sticky="w", pady=(8, 0))
        ttk.Label(reglages, text="(vide = au hasard ; meme seed + meme texte = meme video)", foreground="#666").grid(
            row=1, column=2, columnspan=3, sticky="w", pady=(8, 0))

        boutons = ttk.Frame(self)
        boutons.pack(fill="x", padx=12, pady=10)
        self.btn_go = ttk.Button(boutons, text="Creer la video", command=self.lancer)
        self.btn_go.pack(side="left")
        self.btn_stop = ttk.Button(boutons, text="Arreter", command=self.arreter, state="disabled")
        self.btn_stop.pack(side="left", padx=8)
        self.btn_voir = ttk.Button(boutons, text="Voir la video", command=self.voir, state="disabled")
        self.btn_voir.pack(side="left")
        ttk.Button(boutons, text="Ouvrir le dossier des videos", command=self.dossier).pack(side="right")

        self.barre = ttk.Progressbar(self, mode="indeterminate")
        self.barre.pack(fill="x", padx=12)
        self.statut = ttk.Label(self, text="Pret.", foreground="#333")
        self.statut.pack(anchor="w", **pad)

        ttk.Label(self, text="Journal :").pack(anchor="w", padx=12)
        self.journal = scrolledtext.ScrolledText(self, height=12, font=("Consolas", 9), state="disabled")
        self.journal.pack(fill="both", expand=True, padx=12, pady=(0, 12))

        self.protocol("WM_DELETE_WINDOW", self.fermer)
        self.after(500, self.verifier_installation)

    # --- verifications ---------------------------------------------------
    def verifier_installation(self) -> None:
        if not PYTHON.exists() or not MODELS.exists():
            messagebox.showerror("LTX-2", "Installation incomplete : le programme ou les modeles sont introuvables.")
            return
        go = taille_fichier_echange_go()
        if 0 < go < 60:
            messagebox.showwarning(
                "Fichier d'echange trop petit",
                f"Le fichier d'echange de Windows fait {go:.0f} Go, il en faut environ 64.\n\n"
                "La creation risque d'echouer (erreur 1455). Voir le tuto, section "
                "Problemes frequents, point 1, puis redemarre l'ordinateur.",
            )

    # --- image de depart -----------------------------------------------------
    def choisir_image(self) -> None:
        chemin = filedialog.askopenfilename(
            title="Choisir l'image de depart",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.webp *.bmp"), ("Tous les fichiers", "*.*")],
        )
        if not chemin:
            return
        try:
            with Image.open(chemin) as img:
                largeur, hauteur = img.size
                img.thumbnail((160, 110))
                self.miniature = ImageTk.PhotoImage(img)
        except Exception:
            messagebox.showerror("LTX-2", "Impossible d'ouvrir cette image.")
            return
        self.image = Path(chemin)
        self.apercu.config(image=self.miniature, text="", width=0)
        self.btn_retirer.config(state="normal")
        # On aligne le format de la video sur l'orientation de l'image.
        if largeur > hauteur * 1.15:
            self.format.set("Paysage (768 x 512)")
        elif hauteur > largeur * 1.15:
            self.format.set("Portrait (512 x 768)")
        else:
            self.format.set("Carre (640 x 640)")

    def retirer_image(self) -> None:
        self.image = None
        self.apercu.config(image="", text="Aucune image", width=22)
        self.btn_retirer.config(state="disabled")

    # --- actions -----------------------------------------------------------
    def ecrire(self, texte: str) -> None:
        # Copie du journal sur le disque, pour pouvoir diagnostiquer apres coup.
        try:
            OUTPUTS.mkdir(exist_ok=True)
            with open(OUTPUTS / "derniere_creation.log", "a", encoding="utf-8") as f:
                f.write(texte + "\n")
        except OSError:
            pass
        self.journal.config(state="normal")
        self.journal.insert("end", texte + "\n")
        self.journal.see("end")
        self.journal.config(state="disabled")

    def lancer(self) -> None:
        prompt = self.prompt.get("1.0", "end").strip()
        if not prompt:
            messagebox.showinfo("LTX-2", "Ecris d'abord une description de la video.")
            return
        seed_txt = self.seed.get().strip()
        if seed_txt and not seed_txt.isdigit():
            messagebox.showinfo("LTX-2", "Le seed doit etre un nombre entier (ou vide).")
            return
        seed = int(seed_txt) if seed_txt else random.randint(0, 99999)
        secondes = round(self.duree.get())
        frames = round(secondes * 24 / 8) * 8 + 1  # le modele attend 8k+1 images (24 images/s)
        largeur, hauteur = FORMATS[self.format.get()]

        OUTPUTS.mkdir(exist_ok=True)
        sortie = OUTPUTS / f"video_{datetime.now():%Y-%m-%d_%H-%M-%S}.mp4"
        cmd = [
            str(PYTHON), "-m", "ltx_pipelines.distilled",
            "--transformer-path", str(MODELS / "diffusion_models/ltx-2.5-22b-distilled-transformer-bf16.safetensors"),
            "--text-encoder-path", str(MODELS / "text_encoders/gemma4-12b-with-proj-ltx-2.5-bf16.safetensors"),
            "--video-vae-path", str(MODELS / "vae/ltx-2.5-video-vae-conv-bf16.safetensors"),
            "--audio-vae-path", str(MODELS / "vae/ltx-2.5-audio-vae-bf16.safetensors"),
            "--spatial-upsampler-path",
            str(MODELS / "latent_upscale_models/ltx-2.5-latent-spatial-upscaler-x2-bf16-1.0.safetensors"),
            "--quantization", "fp8-cast", "--offload", "disk",
            "--width", str(largeur), "--height", str(hauteur),
            "--num-frames", str(frames), "--seed", str(seed),
            "--output-path", str(sortie), "--prompt", prompt,
        ]
        if self.image:
            if not self.image.exists():
                messagebox.showerror("LTX-2", "L'image choisie n'existe plus. Choisis-en une autre.")
                return
            cmd += ["--image", str(self.image), "0", "1.0"]  # image placee sur la 1re image, force maximale

        self.journal.config(state="normal")
        self.journal.delete("1.0", "end")
        self.journal.config(state="disabled")
        (OUTPUTS / "derniere_creation.log").write_text("", encoding="utf-8")
        self.ecrire(f"Video de {secondes} s, {largeur}x{hauteur}, seed {seed}")
        if self.image:
            self.ecrire(f"Image de depart : {self.image.name}")
        self.ecrire("Chargement des modeles... (plusieurs minutes, c'est normal)")
        self.statut.config(text="Creation en cours... ne ferme pas la fenetre.")
        self.btn_go.config(state="disabled")
        self.btn_stop.config(state="normal")
        self.btn_voir.config(state="disabled")
        self.barre.start(15)
        self.debut = datetime.now()

        env = dict(os.environ, PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8")
        self.process = subprocess.Popen(
            cmd, cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        threading.Thread(target=self.suivre, args=(self.process, sortie), daemon=True).start()
        self.chrono()

    def chrono(self) -> None:
        if self.process and self.process.poll() is None:
            ecoule = datetime.now() - self.debut
            m, s = divmod(int(ecoule.total_seconds()), 60)
            self.statut.config(text=f"Creation en cours... {m} min {s:02d} s ecoulees. Ne ferme pas la fenetre.")
            self.after(1000, self.chrono)

    def suivre(self, process: subprocess.Popen, sortie: Path) -> None:
        # Les barres de progression du programme se reecrivent avec "\r" : on garde la derniere.
        tampon = b""
        while True:
            octet = process.stdout.read(1)
            if not octet:
                break
            if octet in (b"\r", b"\n"):
                ligne = tampon.decode("utf-8", errors="replace").strip()
                tampon = b""
                if ligne:
                    if octet == b"\n":
                        self.after(0, self.ecrire, ligne)
                    else:
                        self.after(0, lambda l=ligne: self.statut.config(text=l[:140]))
            else:
                tampon += octet
        process.wait()
        self.after(0, self.fin, process.returncode, sortie)

    def fin(self, code: int, sortie: Path) -> None:
        self.barre.stop()
        self.btn_go.config(state="normal")
        self.btn_stop.config(state="disabled")
        self.process = None
        if code == 0 and sortie.exists():
            self.derniere_video = sortie
            self.btn_voir.config(state="normal")
            self.statut.config(text=f"Termine ! Video enregistree : {sortie.name}")
            self.ecrire(f"\nVideo prete : {sortie}")
            self.voir()
        else:
            self.statut.config(text="Echec de la creation. Regarde la fin du journal.")
            texte = self.journal.get("1.0", "end")
            if "1455" in texte or "pagination" in texte:
                messagebox.showerror("LTX-2", "Fichier d'echange Windows trop petit (erreur 1455).\n"
                                              "Voir le tuto, section Problemes frequents, point 1.")
            elif "out of memory" in texte.lower():
                messagebox.showerror("LTX-2", "Memoire de la carte graphique saturee.\n"
                                              "Essaie une duree plus courte et ferme les autres logiciels.")

    def arreter(self) -> None:
        if self.process and self.process.poll() is None:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(self.process.pid)],
                           capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW)
            self.ecrire("\nArrete par l'utilisateur.")

    def voir(self) -> None:
        if self.derniere_video and self.derniere_video.exists():
            os.startfile(self.derniere_video)

    def dossier(self) -> None:
        OUTPUTS.mkdir(exist_ok=True)
        os.startfile(OUTPUTS)

    def fermer(self) -> None:
        if self.process and self.process.poll() is None:
            if not messagebox.askyesno("LTX-2", "Une video est en cours de creation. Arreter et quitter ?"):
                return
            self.arreter()
        self.destroy()


if __name__ == "__main__":
    if sys.platform != "win32":
        sys.exit("Cette interface est prevue pour Windows.")
    App().mainloop()
