# YouTube Music Downloader

Um aplicativo Python simples para baixar músicas do YouTube Music e convertê-las para o formato MP3 com metadados e capa do álbum.

## Requisitos

- Python 3.6 ou superior
- FFmpeg instalado e disponível no sistema PATH

### Bibliotecas Python necessárias
```bash
pip install yt-dlp
pip install pillow
pip install requests
```

## Instalação

1. Certifique-se de ter o Python instalado no seu sistema
2. Instale o FFmpeg:
- Windows: Baixe do [site do FFmpeg](https://ffmpeg.org/download.html) e adicione ao PATH
- Linux: `sudo apt install ffmpeg`
- Mac: `brew install ffmpeg`
3. Instale as bibliotecas Python necessárias:
```bash
pip install -r requirements.txt
```

## Uso

1. Execute o aplicativo:
```bash
python main.py
```
2. Insira uma URL do YouTube Music (única música ou lista de reprodução)
3. Clique no botão "Download"
4. O aplicativo irá:
- Baixar o áudio
- Converte para o formato MP3
- Adiciona metadados e capa do álbum
- Salva em uma pasta com o nome da playlist (ou "Music" para músicas individuais)

## Recursos

- Baixa faixas individuais ou playlists inteiras
- Converte para MP3 de alta qualidade (320 kbps)
- Adiciona metadados (artista, título)
- Incorpora capa do álbum
- Acompanhamento do progresso
- Exibição do log de download

## Notas

- O aplicativo requer uma conexão ativa com a internet
- Os arquivos baixados são salvos no mesmo diretório que o script
- Certifique-se de ter espaço em disco suficiente para downloads