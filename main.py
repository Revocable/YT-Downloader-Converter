import tkinter as tk
from tkinter import ttk, messagebox
import yt_dlp
from yt_dlp.utils import DownloadError # Importar o erro específico
import threading
import os
import queue
import subprocess
import requests
from io import BytesIO
from PIL import Image
import json
import time
import shutil
import re

from mutagen.id3 import ID3, TIT2, TPE1, TALB, TDRC, TCON, APIC, USLT
from mutagen.mp4 import MP4, MP4Cover

# --- CONFIGURAÇÕES GLOBAIS ---
ACOUSTID_API_KEY = "hOukqkaJcv"
USER_AGENT = "MusicDownloaderApp/5.2 (github.com/Revocable/YT-Downloader-Converter)"

NUM_DOWNLOADERS = 4
NUM_PROCESSORS = os.cpu_count() or 4
DOWNLOAD_RETRIES = 3 # Número de tentativas para cada download

def clean_filename(filename):
    return re.sub(r'[\\/*?:"<>|]', "", filename)

class MetadataTagger:
    # A classe MetadataTagger permanece exatamente a mesma
    def __init__(self, log_callback):
        self.log_callback = log_callback
        self.fpcalc_path = shutil.which("fpcalc") or "fpcalc.exe"
        if not os.path.exists(self.fpcalc_path):
            messagebox.showerror("Erro Crítico", "fpcalc.exe não encontrado!")
            raise FileNotFoundError("fpcalc.exe não encontrado.")

    def get_fingerprint(self, file_path):
        try:
            process = subprocess.run([self.fpcalc_path, "-json", file_path], capture_output=True, text=True, check=True, encoding='utf-8')
            data = json.loads(process.stdout)
            return data.get('duration'), data.get('fingerprint')
        except Exception: return None, None
    def lookup_acoustid(self, fingerprint, duration):
        try:
            url = "https://api.acoustid.org/v2/lookup"
            params = {"client": ACOUSTID_API_KEY, "meta": "recordings", "duration": int(duration), "fingerprint": fingerprint}
            response = requests.get(url, params=params, headers={"User-Agent": USER_AGENT}, timeout=10)
            response.raise_for_status()
            data = response.json()
            if data.get('status') == 'ok' and data.get('results'):
                for result in data['results']:
                    if 'recordings' in result and result['recordings']: return result['recordings'][0]['id']
            return None
        except requests.RequestException: return None
    def get_musicbrainz_data(self, recording_id):
        try:
            url = f"https://musicbrainz.org/ws/2/recording/{recording_id}"
            params = {"inc": "artists+releases+genres", "fmt": "json"}
            response = requests.get(url, params=params, headers={"User-Agent": USER_AGENT}, timeout=10)
            response.raise_for_status()
            data = response.json()
            metadata = {'title': data.get('title'),'artist': data['artist-credit'][0]['name'] if data.get('artist-credit') else None,'album': data['releases'][0]['title'] if data.get('releases') else None,'year': data['releases'][0]['date'].split('-')[0] if data.get('releases') and data['releases'][0].get('date') else None,'genre': data['genres'][0]['name'] if data.get('genres') else None,'release_id': data['releases'][0]['id'] if data.get('releases') else None}
            return metadata
        except (requests.RequestException, KeyError, IndexError, TypeError): return None
    def get_cover_art(self, release_id):
        try:
            url = f"https://coverartarchive.org/release/{release_id}"
            response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if data.get('images'):
                    image_url = data['images'][0]['thumbnails'].get('large') or data['images'][0]['image']
                    image_response = requests.get(image_url, headers={"User-Agent": USER_AGENT}, timeout=15)
                    image_response.raise_for_status()
                    return image_response.content
            return None
        except requests.RequestException: return None
    def get_lyrics(self, track_name, artist_name):
        if not track_name or not artist_name: return None
        try:
            response = requests.get("https://lrclib.net/api/search", params={"track_name": track_name, "artist_name": artist_name}, headers={"User-Agent": USER_AGENT}, timeout=10)
            if response.status_code == 200 and response.json():
                for record in response.json():
                    if record.get('syncedLyrics'): return record['syncedLyrics']
            return None
        except requests.RequestException: return None
    def embed_metadata_mp3(self, file_path, metadata, cover_data, lyrics_data):
        try:
            audio = ID3()
            if metadata.get('title'): audio.add(TIT2(encoding=3, text=metadata['title']))
            if metadata.get('artist'): audio.add(TPE1(encoding=3, text=metadata['artist']))
            if metadata.get('album'): audio.add(TALB(encoding=3, text=metadata['album']))
            if metadata.get('year'): audio.add(TDRC(encoding=3, text=str(metadata['year'])))
            if metadata.get('genre'): audio.add(TCON(encoding=3, text=metadata['genre']))
            if cover_data: audio.add(APIC(encoding=3, mime='image/jpeg', type=3, desc='Cover', data=cover_data))
            if lyrics_data: audio.add(USLT(encoding=3, lang='eng', desc='lyrics', text=lyrics_data))
            audio.save(file_path, v2_version=4)
            return True
        except Exception as e:
            self.log_callback(f"[METADATA] Erro ao salvar tags MP3: {e}")
            return False
    def embed_metadata_m4a(self, file_path, metadata, cover_data, lyrics_data):
        try:
            audio = MP4(file_path)
            if metadata.get('title'): audio['\xa9nam'] = [metadata['title']]
            if metadata.get('artist'): audio['\xa9ART'] = [metadata['artist']]
            if metadata.get('album'): audio['\xa9alb'] = [metadata['album']]
            if metadata.get('year'): audio['\xa9day'] = [str(metadata['year'])]
            if metadata.get('genre'): audio['\xa9gen'] = [metadata['genre']]
            if cover_data: audio['covr'] = [MP4Cover(cover_data, imageformat=MP4Cover.FORMAT_JPEG)]
            if lyrics_data: audio['\xa9lyr'] = [lyrics_data]
            audio.save()
            return True
        except Exception as e:
            self.log_callback(f"[METADATA] Erro ao salvar tags M4A: {e}")
            return False
    def process_and_embed(self, file_path, embed_function):
        filename = os.path.basename(file_path)
        self.log_callback(f"[TAGGER] Gerando fingerprint para '{filename}'...")
        duration, fingerprint = self.get_fingerprint(file_path)
        if not fingerprint: return None
        time.sleep(0.1)
        mb_recording_id = self.lookup_acoustid(fingerprint, duration)
        if not mb_recording_id:
            self.log_callback(f"[TAGGER] Música não encontrada: '{filename}'.")
            return None
        time.sleep(0.1)
        metadata = self.get_musicbrainz_data(mb_recording_id)
        if not metadata:
            self.log_callback(f"[TAGGER] Dados não encontrados: '{filename}'.")
            return None
        self.log_callback(f"[TAGGER] Encontrado: {metadata['artist']} - {metadata['title']}")
        cover_data, lyrics_data = None, None
        if metadata.get('release_id'):
            time.sleep(0.1)
            cover_data = self.get_cover_art(metadata['release_id'])
        if metadata.get('title') and metadata.get('artist'):
            time.sleep(0.1)
            lyrics_data = self.get_lyrics(metadata['title'], metadata['artist'])
        if embed_function(file_path, metadata, cover_data, lyrics_data):
            self.log_callback(f"[TAGGER] Sucesso! Tags salvas para '{filename}'.")
            return metadata
        else:
            self.log_callback(f"[TAGGER] Falha ao salvar tags para '{filename}'.")
            return None

class MusicDownloaderApp:
    def __init__(self, root):
        self.root = root
        self.root.title("YouTube Music Downloader & Tagger PRO v5.2 (Resilient)")
        self.root.geometry("600x600")
        try:
            self.tagger = MetadataTagger(self.add_log)
        except FileNotFoundError:
            self.root.destroy()
            return
        self.setup_widgets()
        self.setup_state()

    def setup_widgets(self):
        self.label_url = tk.Label(self.root, text="Insira o link da música ou playlist do YouTube/Music:")
        self.label_url.pack(pady=(10, 5))
        self.entry_url = tk.Entry(self.root, width=80)
        self.entry_url.pack(pady=5, padx=20)
        format_frame = tk.Frame(self.root)
        format_frame.pack(pady=5)
        self.format_choice = tk.StringVar(value="mp3")
        tk.Label(format_frame, text="Escolha o formato de saída:").pack(side=tk.LEFT, padx=(0, 10))
        mp3_button = tk.Radiobutton(format_frame, text="MP3 (320kbps)", variable=self.format_choice, value="mp3")
        mp3_button.pack(side=tk.LEFT)
        m4a_button = tk.Radiobutton(format_frame, text="M4A/AAC (256kbps)", variable=self.format_choice, value="m4a")
        m4a_button.pack(side=tk.LEFT)
        self.btn_baixar = tk.Button(self.root, text="Baixar, Converter e Taguear", command=self.iniciar_download)
        self.btn_baixar.pack(pady=10)
        progress_frame = tk.Frame(self.root)
        progress_frame.pack(pady=10, fill=tk.X, padx=20)
        self.download_progress_label = tk.Label(progress_frame, text="Progresso de Download:")
        self.download_progress_label.pack()
        self.download_progress_bar = ttk.Progressbar(progress_frame, orient='horizontal', length=400, mode='determinate')
        self.download_progress_bar.pack(pady=5)
        self.processing_progress_label = tk.Label(progress_frame, text="Progresso de Processamento:")
        self.processing_progress_label.pack()
        self.processing_progress_bar = ttk.Progressbar(progress_frame, orient='horizontal', length=400, mode='determinate')
        self.processing_progress_bar.pack(pady=5)
        log_frame = tk.Frame(self.root)
        log_frame.pack(pady=10, padx=20, fill=tk.BOTH, expand=True)
        self.log_text = tk.Text(log_frame, height=10, state='disabled', bg='#f0f0f0', fg='black')
        log_scrollbar = tk.Scrollbar(log_frame, command=self.log_text.yview)
        self.log_text.config(yscrollcommand=log_scrollbar.set)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        log_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
    
    def setup_state(self):
        self.url_queue = queue.Queue()
        self.processing_queue = queue.Queue()
        self.download_count = 0
        self.processing_count = 0
        self.failure_count = 0
        self.failed_urls = []
        self.total_musicas = 0
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.is_running = False

    def on_closing(self):
        if self.is_running and messagebox.askokcancel("Sair", "Um processo está em andamento. Deseja realmente sair?"):
            self.root.destroy()
        elif not self.is_running:
            self.root.destroy()

    def add_log(self, message):
        if self.root.winfo_exists(): self.root.after(0, self._add_log_gui, message)

    def _add_log_gui(self, message):
        self.log_text.config(state='normal')
        if "[DOWNLOAD]" in message:
            last_line_start = self.log_text.index("end-1l")
            last_line_content = self.log_text.get(last_line_start, "end-1c")
            if "[DOWNLOAD]" in last_line_content:
                self.log_text.delete(last_line_start, "end-1c")
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.config(state='disabled')
        self.log_text.yview(tk.END)

    def update_progress(self):
        if self.root.winfo_exists(): self.root.after(0, self._update_progress_gui)

    def _update_progress_gui(self):
        # ### MUDANÇA: A barra de download agora considera sucessos + falhas ###
        total_downloads_attempted = self.download_count + self.failure_count
        dl_p = (total_downloads_attempted / self.total_musicas) * 100 if self.total_musicas > 0 else 0
        proc_p = (self.processing_count / self.download_count) * 100 if self.download_count > 0 else 0
        
        self.download_progress_bar['value'] = dl_p
        self.download_progress_label.config(text=f"Progresso de Download: {total_downloads_attempted}/{self.total_musicas}")
        
        # A barra de processamento só considera os downloads bem-sucedidos
        self.processing_progress_bar['value'] = proc_p
        self.processing_progress_label.config(text=f"Progresso de Processamento: {self.processing_count}/{self.download_count}")

    def iniciar_download(self):
        url = self.entry_url.get()
        if not url: return messagebox.showerror("Erro", "Por favor, insira um link.")
        self.btn_baixar.config(state='disabled')
        self.is_running = True
        self.add_log("Iniciando pipeline...")
        chosen_format = self.format_choice.get()
        threading.Thread(target=self.run_pipeline, args=(url, chosen_format), daemon=True).start()

    def downloader_worker(self, output_template):
        class YtdlpLogger:
            def __init__(self, log_callback): self.log_callback = log_callback
            def debug(self, msg):
                if msg.startswith('[download] Destination: '): self.last_filename = os.path.basename(msg.split('Destination: ')[1])
                elif msg.startswith('[download]'):
                    cleaned_msg = re.sub(r'\s+', ' ', msg).strip()
                    log_msg = f"[DOWNLOAD] {getattr(self, 'last_filename', '')} - {cleaned_msg.replace('[download] ', '')}"
                    self.log_callback(log_msg)
            def warning(self, msg): self.log_callback(f"[AVISO YT] {msg}")
            def error(self, msg): self.log_callback(f"[ERRO YT] {msg}")

        ydl_opts = {'format': 'bestaudio/best', 'outtmpl': output_template, 'cookies_from_browser': ('brave', 'cookies.txt'), 'logger': YtdlpLogger(self.add_log), 'progress_hooks': [self.ytdlp_hook],}
        
        if not os.path.exists('cookies.txt'):
            self.add_log("[ERRO CRÍTICO] Arquivo 'cookies.txt' não encontrado.")
            # Esvazia a fila para não deixar outras threads esperando
            while not self.url_queue.empty():
                try: self.url_queue.get_nowait(); self.url_queue.task_done()
                except queue.Empty: break
            return

        while True:
            try:
                video_url = self.url_queue.get_nowait()
                download_successful = False
                for attempt in range(DOWNLOAD_RETRIES):
                    try:
                        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                            ydl.download([video_url])
                        download_successful = True
                        break # Sai do loop de retentativas se o download for bem-sucedido
                    except DownloadError as e:
                        self.add_log(f"[AVISO DOWNLOAD] Tentativa {attempt + 1}/{DOWNLOAD_RETRIES} falhou para {video_url[-15:]}: {e.msg.split(':')[-1].strip()}")
                        time.sleep(2) # Espera 2 segundos antes de tentar novamente
                
                if not download_successful:
                    self.add_log(f"[ERRO FATAL] Não foi possível baixar {video_url[-15:]} após {DOWNLOAD_RETRIES} tentativas.")
                    self.failure_count += 1
                    self.failed_urls.append(video_url)
                    self.update_progress()

                self.url_queue.task_done()
            except queue.Empty:
                break
    
    def ytdlp_hook(self, d):
        if d['status'] == 'finished':
            # Só coloca na fila de processamento se o download terminar com sucesso
            self.processing_queue.put(d['filename'])
            self.download_count += 1
            self.update_progress()
    
    def processor_worker(self, chosen_format):
        while True:
            try:
                temp_path = self.processing_queue.get(timeout=1)
                try:
                    self.add_log(f"[PROCESSADOR] Processando: {os.path.basename(temp_path)}")
                    base_path, _ = os.path.splitext(temp_path)
                    if chosen_format == "m4a":
                        output_ext = ".m4a"; ffmpeg_cmd = ['ffmpeg', '-y', '-i', temp_path, '-vn', '-c:a', 'aac', '-b:a', '256k', '-hide_banner', '-loglevel', 'error']; embed_func = self.tagger.embed_metadata_m4a
                    else:
                        output_ext = ".mp3"; ffmpeg_cmd = ['ffmpeg', '-y', '-i', temp_path, '-vn', '-c:a', 'libmp3lame', '-b:a', '320k', '-hide_banner', '-loglevel', 'error']; embed_func = self.tagger.embed_metadata_mp3
                    output_path = f"{base_path}{output_ext}"
                    ffmpeg_cmd.append(output_path)
                    subprocess.run(ffmpeg_cmd, check=True, capture_output=True)
                    final_metadata = self.tagger.process_and_embed(output_path, embed_func)
                    if final_metadata and final_metadata.get('artist') and final_metadata.get('title'):
                        artist = clean_filename(final_metadata['artist']); title = clean_filename(final_metadata['title']); directory = os.path.dirname(output_path)
                        new_filename = f"{artist} - {title}{output_ext}"; new_filepath = os.path.join(directory, new_filename)
                        if output_path != new_filepath:
                            if os.path.exists(new_filepath): self.add_log(f"[AVISO] Arquivo '{new_filename}' já existe.")
                            else: os.rename(output_path, new_filepath); self.add_log(f"[RENOMEADO] para '{new_filename}'")
                    self.processing_count += 1
                    self.update_progress()
                except Exception as e:
                    self.add_log(f"[ERRO PROCESSADOR] Falha em {os.path.basename(temp_path or 'arquivo')}: {e}")
                finally:
                    if os.path.exists(temp_path): os.remove(temp_path)
                    if 'output_path' in locals() and os.path.exists(output_path) and not ('new_filepath' in locals() and os.path.exists(new_filepath)): os.remove(output_path)
                self.processing_queue.task_done()
            except queue.Empty:
                if self.url_queue.empty(): break
    
    def run_pipeline(self, url, chosen_format):
        try:
            with yt_dlp.YoutubeDL({'quiet': True, 'extract_flat': True, 'ignoreerrors': True}) as ydl: info = ydl.extract_info(url, download=False)
            entries = info.get('entries', [info])
            playlist_folder = info.get('title', 'Músicas Avulsas').replace('/', '_').replace('\\', '_')
            output_template = os.path.join(playlist_folder, '%(title)s.%(ext)s')
            output_dir = os.path.dirname(output_template)
            if not os.path.exists(output_dir): os.makedirs(output_dir)
            self.total_musicas = len(entries)
            self.add_log(f"Encontradas {self.total_musicas} músicas. Formato de saída: {chosen_format.upper()}")
            self.update_progress()
            for entry in entries: self.url_queue.put(entry['url'])
            downloader_threads = [threading.Thread(target=self.downloader_worker, args=(output_template,), daemon=True) for _ in range(NUM_DOWNLOADERS)]
            processor_threads = [threading.Thread(target=self.processor_worker, args=(chosen_format,), daemon=True) for _ in range(NUM_PROCESSORS)]
            for t in downloader_threads: t.start()
            for t in processor_threads: t.start()
            self.url_queue.join()
            self.add_log("--- Fila de downloads concluída. Aguardando processamento... ---")
            self.processing_queue.join()
            self.add_log("--- Fila de processamento concluída. ---")
            
            # ### NOVO: Relatório final de falhas ###
            if self.failed_urls:
                failed_list = "\n".join([f"- {url}" for url in self.failed_urls])
                messagebox.showwarning("Processo Concluído com Falhas", f"{len(self.failed_urls)} música(s) não puderam ser baixadas:\n\n{failed_list}")
            else:
                messagebox.showinfo("Sucesso", "Processo concluído com sucesso!")
            self.add_log("--- Processo finalizado! ---")
        except Exception as e:
            self.add_log(f"[ERRO CRÍTICO] Falha no pipeline: {e}")
            messagebox.showerror("Erro Crítico", f"Ocorreu uma falha grave: {e}")
        finally:
            self.btn_baixar.config(state='normal')
            self.is_running = False
            self.download_count = self.processing_count = self.failure_count = self.total_musicas = 0
            self.failed_urls = []

if __name__ == "__main__":
    root = tk.Tk()
    app = MusicDownloaderApp(root)
    if hasattr(app, 'tagger') and app.tagger:
        root.mainloop()