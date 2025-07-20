import tkinter as tk
from tkinter import ttk, messagebox
import yt_dlp
import threading
import os

# Classe principal da aplicação
class MusicDownloaderApp:
    def __init__(self, root):
        self.root = root
        self.root.title("YouTube Music Downloader by AI")
        self.root.geometry("500x450")

        # --- Widgets da Interface ---
        self.label_url = tk.Label(root, text="Insira o link da música ou playlist do YouTube/Music:")
        self.label_url.pack(pady=(10, 5))

        self.entry_url = tk.Entry(root, width=60)
        self.entry_url.pack(pady=5, padx=20)

        self.btn_baixar = tk.Button(root, text="Baixar e Converter", command=self.iniciar_download)
        self.btn_baixar.pack(pady=10)
        
        # Frame para os progressos
        progress_frame = tk.Frame(root)
        progress_frame.pack(pady=10, fill=tk.X, padx=20)

        self.status_label = tk.Label(progress_frame, text="Aguardando link...")
        self.status_label.pack()
        
        self.progress_bar = ttk.Progressbar(progress_frame, orient='horizontal', length=400, mode='determinate')
        self.progress_bar.pack(pady=5)
        
        self.total_progress_label = tk.Label(progress_frame, text="")
        self.total_progress_label.pack()
        
        self.total_progress_bar = ttk.Progressbar(progress_frame, orient='horizontal', length=400, mode='determinate')
        self.total_progress_bar.pack(pady=5)

        # Log de atividades
        self.log_text = tk.Text(root, height=10, width=50, state='disabled')
        log_scrollbar = tk.Scrollbar(root, command=self.log_text.yview)
        self.log_text.config(yscrollcommand=log_scrollbar.set)
        
        self.log_text.pack(pady=10, padx=20, side=tk.LEFT, fill=tk.BOTH, expand=True)
        log_scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.download_count = 0
        self.total_musicas = 0

    def add_log(self, message):
        """ Adiciona uma mensagem ao log da interface """
        self.log_text.config(state='normal')
        self.log_text.insert(tk.END, message + "\n")
        self.log_text.config(state='disabled')
        self.log_text.yview(tk.END)

    def progress_hook(self, d):
        """ Hook chamado pelo yt-dlp durante o download """
        if d['status'] == 'finished':
            # Quando um arquivo termina de ser processado (download + conversão)
            filename = d.get('filename', 'arquivo')
            base_name = os.path.basename(filename)
            self.add_log(f"[CONCLUÍDO] {base_name}")
            
            # Atualiza a barra de progresso total
            self.download_count += 1
            progress_percent = (self.download_count / self.total_musicas) * 100
            self.total_progress_bar['value'] = progress_percent
            self.total_progress_label.config(text=f"Progresso Total: {self.download_count}/{self.total_musicas}")
            self.root.update_idletasks()

        if d['status'] == 'downloading':
            # Atualiza o status do download atual
            percent_str = d.get('_percent_str', '0.0%').strip()
            speed_str = d.get('_speed_str', '0 B/s').strip()
            eta_str = d.get('_eta_str', 'N/A').strip()
            
            try:
                # Extrai o valor numérico da porcentagem
                progress_value = float(percent_str.replace('%', ''))
                self.progress_bar['value'] = progress_value
            except ValueError:
                self.progress_bar['value'] = 0
            
            self.status_label.config(text=f"Baixando: {percent_str} a {speed_str} (ETA: {eta_str})")
            self.root.update_idletasks()

    def iniciar_download(self):
        url = self.entry_url.get()
        if not url:
            messagebox.showerror("Erro", "Por favor, insira um link.")
            return

        # Desabilitar botão para evitar cliques duplos
        self.btn_baixar.config(state='disabled')
        self.status_label.config(text="Analisando o link...")
        self.progress_bar['value'] = 0
        self.total_progress_bar['value'] = 0
        self.download_count = 0
        self.total_musicas = 0
        
        # Inicia o processo de download em uma thread separada para não travar a GUI
        download_thread = threading.Thread(target=self.run_download_thread, args=(url,))
        download_thread.start()

    def run_download_thread(self, url):
        try:
            # 1. Obter informações da playlist/vídeo para saber quantos itens baixar
            with yt_dlp.YoutubeDL({'quiet': True, 'extract_flat': True}) as ydl:
                info = ydl.extract_info(url, download=False)
                if 'entries' in info:
                    # É uma playlist
                    self.total_musicas = len(info['entries'])
                    playlist_folder = info.get('title', 'Playlist').replace('/', '_').replace('\\', '_')
                    output_template = os.path.join(playlist_folder, '%(title)s.%(ext)s')
                else:
                    # É um vídeo único
                    self.total_musicas = 1
                    output_template = os.path.join('Músicas Avulsas', '%(title)s.%(ext)s')
            
            self.add_log(f"Iniciando download de {self.total_musicas} música(s)...")
            self.total_progress_label.config(text=f"Progresso Total: 0/{self.total_musicas}")
            
            # 2. Configurar as opções de download e pós-processamento
            ydl_opts = {
                'format': 'bestaudio/best',
                'outtmpl': output_template,
                'progress_hooks': [self.progress_hook],
                'ignoreerrors': True, # Não para o download se uma música falhar
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '320', # Qualidade de 320k
                }, {
                    'key': 'EmbedThumbnail', # Incorpora a capa do álbum
                }, {
                    'key': 'FFmpegMetadata', # Garante que os metadados sejam escritos
                }],
            }
            
            # 3. Executar o download
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([url])

            self.status_label.config(text="Download e conversão concluídos!")
            messagebox.showinfo("Sucesso", "Todas as músicas foram baixadas e convertidas com sucesso!")

        except Exception as e:
            self.status_label.config(text="Ocorreu um erro.")
            self.add_log(f"[ERRO] {str(e)}")
            messagebox.showerror("Erro", f"Ocorreu um erro: {str(e)}")
        finally:
            # Reabilitar o botão ao final do processo
            self.btn_baixar.config(state='normal')

if __name__ == "__main__":
    root = tk.Tk()
    app = MusicDownloaderApp(root)
    root.mainloop()