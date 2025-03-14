import yt_dlp
import threading
import tkinter as tk
from tkinter import messagebox
from tkinter import ttk
import os
import subprocess
import requests
from io import BytesIO
from PIL import Image

# Baixar e converter músicas
def baixar_musica(url, log_text, destino, progresso, total_musicas):
    ydl_opts = {
        'format': 'bestaudio[ext=m4a]',
        'audio_quality': 0,
        'extractaudio': True,
        'outtmpl': os.path.join(destino, '%(title)s.%(ext)s'),
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info_dict = ydl.extract_info(url, download=False)
        title = info_dict.get('title', 'Desconhecido').replace("/", "-")
        artist = info_dict.get('uploader', 'Desconhecido')
        thumbnail_url = info_dict.get('thumbnail', '')
        
        ydl.download([url])
        
        img_path = None
        if thumbnail_url:
            try:
                img_data = requests.get(thumbnail_url).content
                img = Image.open(BytesIO(img_data))
                img_path = os.path.join(destino, f"{title}_cover.jpg")
                img.convert('RGB').save(img_path)
            except Exception as e:
                log_text.insert(tk.END, f"Erro ao baixar imagem: {str(e)}\n")

        audio_file = os.path.join(destino, f"{title}.m4a")
        mp3_file = os.path.join(destino, f"{title}.mp3")
        
        if os.path.exists(audio_file):
            try:
                ffmpeg_cmd = [
                    'ffmpeg',
                    '-i', audio_file,
                    '-i', img_path,
                    '-map', '0:a',
                    '-map', '1',
                    '-c:a', 'libmp3lame',
                    '-b:a', '320k',
                    '-id3v2_version', '3',
                    '-metadata', f'artist={artist}',
                    '-metadata', f'title={title}',
                    '-metadata:s:v', 'title="Album cover"',
                    '-metadata:s:v', 'comment="Cover (front)"',
                    '-disposition:v', 'attached_pic',
                    mp3_file
                ]
                subprocess.run(ffmpeg_cmd, check=True, capture_output=True)

            except subprocess.CalledProcessError as e:
                log_text.insert(tk.END, f"Erro FFmpeg: {e.stderr.decode()}\n")
            except Exception as e:
                log_text.insert(tk.END, f"Erro geral: {str(e)}\n")
            finally:
                if os.path.exists(audio_file):
                    os.remove(audio_file)
                if img_path and os.path.exists(img_path):
                    os.remove(img_path)

        log_text.insert(tk.END, f"Finalizado: {title}\n")
        log_text.yview(tk.END)
        progresso['value'] += (100 / total_musicas)
        progresso.update()

def converter_musicas(destino):
    def converter_audio(caminho_arquivo):
        try:
            output_file = os.path.splitext(caminho_arquivo)[0] + ".mp3"
            subprocess.run([
                'ffmpeg', '-i', caminho_arquivo, '-vn', '-ar', '44100', '-ac', '2',
                '-b:a', '320k', '-map_metadata', '0', output_file
            ], check=True)
            os.remove(caminho_arquivo)
        except Exception as e:
            print(f"Erro ao converter {caminho_arquivo}: {str(e)}")

    for root_dir, dirs, files in os.walk(destino):
        for file in files:
            if file.endswith(('.m4a', '.mp3')):
                caminho_arquivo = os.path.join(root_dir, file)
                threading.Thread(target=converter_audio, args=(caminho_arquivo,)).start()

# Interface gráfica e thread de download
def baixar():
    url = entry_url.get()
    if not url:
        messagebox.showerror("Erro", "Por favor, insira o link da música ou playlist.")
        return
    
    ydl_opts = {
        'quiet': True,
        'extract_flat': True,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        try:
            info_dict = ydl.extract_info(url, download=False)
            if 'entries' in info_dict:
                urls = [entry['url'] for entry in info_dict['entries']]
                playlist_name = info_dict.get('title', 'Playlist')
                destino = playlist_name
            else:
                urls = [url]
                playlist_name = "Music"
                destino = "Music"
                
            if not os.path.exists(destino):
                os.makedirs(destino)
        except Exception as e:
            messagebox.showerror("Erro", f"Ocorreu um erro ao processar: {str(e)}")
            return

    total_musicas = len(urls)
    
    progresso = ttk.Progressbar(root, orient='horizontal', length=400, mode='determinate', maximum=100)
    progresso.pack(pady=10)

    def download_thread():
        threads = []
        for url in urls:
            thread = threading.Thread(target=baixar_musica, args=(url, log_text, destino, progresso, total_musicas))
            threads.append(thread)
            thread.start()
        
        for thread in threads:
            thread.join()
        
        converter_musicas(destino)
        messagebox.showinfo("Sucesso", "Download e conversão completos!")

    threading.Thread(target=download_thread).start()

root = tk.Tk()
root.title("Downloader de Música")

label_url = tk.Label(root, text="Insira o link da música ou playlist do YouTube Music:")
label_url.pack(pady=5)

entry_url = tk.Entry(root, width=40)
entry_url.pack(pady=5)

btn_baixar = tk.Button(root, text="Baixar", command=baixar)
btn_baixar.pack(pady=10)

log_text = tk.Text(root, height=10, width=50)
log_text.pack(pady=10)
log_text.insert(tk.END, "Log de downloads:\n")

root.mainloop()
