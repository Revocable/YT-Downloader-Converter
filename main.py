import tkinter as tk
from tkinter import ttk, messagebox
import yt_dlp
import threading
import os
import queue
import subprocess
import requests
from io import BytesIO
from PIL import Image

# --- PARÂMETROS DE PERFORMANCE (AJUSTE CONFORME SEU PC E INTERNET) ---
NUM_DOWNLOADERS = 24 # Número de threads para download (ajuste conforme seu PC)
NUM_CONVERTERS = 24 # 0 = auto-detectar

# Classe principal da aplicação
class MusicDownloaderApp:
    def __init__(self, root):
        self.root = root
        self.root.title("YouTube Music Downloader PRO (Fast & Parallel)")
        self.root.geometry("550x500")

        # Configura o número de conversores
        self.num_converters = NUM_CONVERTERS if NUM_CONVERTERS > 0 else os.cpu_count() or 2

        # --- Widgets da Interface ---
        self.label_url = tk.Label(root, text="Insira o link da música ou playlist do YouTube/Music:")
        self.label_url.pack(pady=(10, 5))
        self.entry_url = tk.Entry(root, width=70)
        self.entry_url.pack(pady=5, padx=20)
        self.btn_baixar = tk.Button(root, text="Baixar e Converter (Rápido)", command=self.iniciar_download)
        self.btn_baixar.pack(pady=10)
        
        progress_frame = tk.Frame(root)
        progress_frame.pack(pady=10, fill=tk.X, padx=20)
        self.download_progress_label = tk.Label(progress_frame, text="Progresso de Download:")
        self.download_progress_label.pack()
        self.download_progress_bar = ttk.Progressbar(progress_frame, orient='horizontal', length=400, mode='determinate')
        self.download_progress_bar.pack(pady=5)
        self.conversion_progress_label = tk.Label(progress_frame, text="Progresso de Conversão:")
        self.conversion_progress_label.pack()
        self.conversion_progress_bar = ttk.Progressbar(progress_frame, orient='horizontal', length=400, mode='determinate')
        self.conversion_progress_bar.pack(pady=5)

        log_frame = tk.Frame(root)
        log_frame.pack(pady=10, padx=20, fill=tk.BOTH, expand=True)
        self.log_text = tk.Text(log_frame, height=10, state='disabled')
        log_scrollbar = tk.Scrollbar(log_frame, command=self.log_text.yview)
        self.log_text.config(yscrollcommand=log_scrollbar.set)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        log_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.url_queue = queue.Queue()
        self.conversion_queue = queue.Queue()
        self.download_count = 0
        self.conversion_count = 0
        self.total_musicas = 0
        self.yt_dlp_lock = threading.Lock()

        ### CORREÇÃO 1: Capturar o evento de fechar a janela ###
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.is_running = False

    def on_closing(self):
        """Função chamada quando o usuário clica no 'X' da janela."""
        if self.is_running:
            # Se um download estiver em andamento, pergunte ao usuário
            if messagebox.askokcancel("Sair", "Um download está em andamento. Deseja realmente sair? O processo será interrompido."):
                self.root.destroy() # A destruição da janela irá encerrar os threads daemon
        else:
            self.root.destroy()

    def add_log(self, message):
        if self.root.winfo_exists():
            self.root.after(0, self._add_log_gui, message)

    def _add_log_gui(self, message):
        self.log_text.config(state='normal')
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.config(state='disabled')
        self.log_text.yview(tk.END)

    def update_progress(self):
        if self.root.winfo_exists():
            self.root.after(0, self._update_progress_gui)

    def _update_progress_gui(self):
        dl_percent = (self.download_count / self.total_musicas) * 100 if self.total_musicas > 0 else 0
        conv_percent = (self.conversion_count / self.total_musicas) * 100 if self.total_musicas > 0 else 0
        self.download_progress_bar['value'] = dl_percent
        self.download_progress_label.config(text=f"Progresso de Download: {self.download_count}/{self.total_musicas}")
        self.conversion_progress_bar['value'] = conv_percent
        self.conversion_progress_label.config(text=f"Progresso de Conversão: {self.conversion_count}/{self.total_musicas}")

    def iniciar_download(self):
        url = self.entry_url.get()
        if not url:
            messagebox.showerror("Erro", "Por favor, insira um link.")
            return

        self.btn_baixar.config(state='disabled')
        self.is_running = True
        self.add_log("Analisando o link...")
        threading.Thread(target=self.run_pipeline, args=(url,), daemon=True).start()

    def downloader_worker(self, output_template):
        ydl_opts = {'format': 'bestaudio[ext=m4a]/bestaudio/best', 'outtmpl': output_template, 'quiet': True}
        while not self.url_queue.empty():
            try:
                video_url = self.url_queue.get_nowait()
                self.add_log(f"[DOWNLOADER] Pegou: {video_url}")
                with self.yt_dlp_lock:
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        info = ydl.extract_info(video_url, download=True)
                filename = yt_dlp.YoutubeDL(ydl_opts).prepare_filename(info)
                file_info = {'input_path': filename, 'title': info.get('title', 'Unknown Title'), 'artist': info.get('uploader', 'Unknown Artist'), 'thumbnail_url': info.get('thumbnail')}
                self.conversion_queue.put(file_info)
                self.download_count += 1
                self.update_progress()
            except queue.Empty:
                break
            except Exception as e:
                self.add_log(f"[ERRO DOWNLOAD] Falha: {e}")
            finally:
                self.url_queue.task_done()
    
    def converter_worker(self):
        while True:
            ### CORREÇÃO 2: Prevenir o UnboundLocalError ###
            # Inicializa as variáveis para garantir que elas existam no bloco finally
            input_path = None
            img_path = None
            
            try:
                file_info = self.conversion_queue.get()
                if file_info is None:
                    break
                
                self.add_log(f"[CONVERTER] Processando: {file_info['title']}")
                input_path = file_info['input_path']
                base_path, _ = os.path.splitext(input_path)
                output_path = f"{base_path}.mp3"
                
                if file_info['thumbnail_url']:
                    try:
                        img_data = requests.get(file_info['thumbnail_url']).content
                        img = Image.open(BytesIO(img_data))
                        img_path = f"{base_path}_cover.jpg"
                        img.convert('RGB').save(img_path)
                    except Exception as e:
                        self.add_log(f"[AVISO] Não foi possível baixar a capa para {file_info['title']}: {e}")

                ffmpeg_cmd = ['ffmpeg', '-y', '-i', input_path]
                if img_path:
                    ffmpeg_cmd.extend(['-i', img_path])
                ffmpeg_cmd.extend(['-c:a', 'libmp3lame', '-b:a', '320k', '-id3v2_version', '3', '-metadata', f"title={file_info['title']}", '-metadata', f"artist={file_info['artist']}"])
                if img_path:
                    ffmpeg_cmd.extend(['-map', '0:a', '-map', '1:v', '-metadata:s:v', 'title="Album cover"', '-metadata:s:v', 'comment="Cover (front)"', '-disposition:v', 'attached_pic'])
                ffmpeg_cmd.append(output_path)
                subprocess.run(ffmpeg_cmd, check=True, capture_output=True, text=True, encoding='utf-8')
                self.conversion_count += 1
                self.update_progress()
                self.add_log(f"[CONCLUÍDO] {os.path.basename(output_path)}")
            except subprocess.CalledProcessError as e:
                self.add_log(f"[ERRO FFMPEG] Em {file_info.get('title', 'arquivo')}: {e.stderr}")
            except Exception as e:
                self.add_log(f"[ERRO CONVERSÃO] Em {file_info.get('title', 'arquivo')}: {e}")
            finally:
                if input_path and os.path.exists(input_path): os.remove(input_path)
                if img_path and os.path.exists(img_path): os.remove(img_path)
                self.conversion_queue.task_done()
    
    def run_pipeline(self, url):
        try:
            # O warning sobre "YouTube Music is not directly supported" é do yt-dlp e inofensivo.
            # Significa apenas que ele está convertendo o link para um de youtube.com.
            with yt_dlp.YoutubeDL({'quiet': True, 'extract_flat': True, 'ignoreerrors': True}) as ydl:
                info = ydl.extract_info(url, download=False)
                if 'entries' in info:
                    entries = info['entries']
                    playlist_folder = info.get('title', 'Playlist').replace('/', '_').replace('\\', '_')
                    output_template = os.path.join(playlist_folder, '%(title)s.%(ext)s')
                else:
                    entries = [info]
                    output_template = os.path.join('Músicas Avulsas', '%(title)s.%(ext)s')
            output_dir = os.path.dirname(output_template)
            if not os.path.exists(output_dir): os.makedirs(output_dir)
            
            self.total_musicas = len(entries)
            self.add_log(f"Encontradas {self.total_musicas} músicas. Iniciando pipeline...")
            self.update_progress()
            for entry in entries: self.url_queue.put(entry['url'])

            threads = []
            for _ in range(NUM_DOWNLOADERS):
                t = threading.Thread(target=self.downloader_worker, args=(output_template,))
                t.daemon = True  ### CORREÇÃO 3: Tornar os threads daemon ###
                threads.append(t)
            for _ in range(self.num_converters):
                t = threading.Thread(target=self.converter_worker)
                t.daemon = True  ### CORREÇÃO 3: Tornar os threads daemon ###
                threads.append(t)
            
            for t in threads: t.start()

            self.url_queue.join()
            self.add_log("--- Fila de downloads vazia. Aguardando conversões... ---")
            for _ in range(self.num_converters): self.conversion_queue.put(None)
            self.conversion_queue.join()

            messagebox.showinfo("Sucesso", "Pipeline concluído! Todas as músicas foram baixadas e convertidas.")
            self.add_log("--- Processo finalizado com sucesso! ---")
        except Exception as e:
            self.add_log(f"[ERRO CRÍTICO] Falha no pipeline: {e}")
            messagebox.showerror("Erro Crítico", f"Ocorreu uma falha grave: {e}")
        finally:
            self.btn_baixar.config(state='normal')
            self.is_running = False
            self.download_count, self.conversion_count, self.total_musicas = 0, 0, 0

if __name__ == "__main__":
    root = tk.Tk()
    app = MusicDownloaderApp(root)
    root.mainloop()