import os
import argparse
# pip install pydrive2 dropbox で利用可
try:
    from pydrive2.auth import GoogleAuth
    from pydrive2.drive import GoogleDrive
except ImportError:
    GoogleAuth = GoogleDrive = None
try:
    import dropbox
except ImportError:
    dropbox = None

def upload_to_gdrive(local_path, folder_id=None):
    if GoogleAuth is None:
        print('pydrive2がインストールされていません')
        return
    gauth = GoogleAuth()
    gauth.LocalWebserverAuth()
    drive = GoogleDrive(gauth)
    fname = os.path.basename(local_path)
    f = drive.CreateFile({'title': fname, 'parents': [{'id': folder_id}] if folder_id else []})
    f.SetContentFile(local_path)
    f.Upload()
    print(f"Google Driveにアップロード: {fname}")

def upload_to_dropbox(local_path, dropbox_token, dropbox_path):
    if dropbox is None:
        print('dropboxパッケージがインストールされていません')
        return
    dbx = dropbox.Dropbox(dropbox_token)
    with open(local_path, 'rb') as f:
        dbx.files_upload(f.read(), dropbox_path, mode=dropbox.files.WriteMode.overwrite)
    print(f"Dropboxにアップロード: {dropbox_path}")

def main():
    parser = argparse.ArgumentParser(description='ファイルをGoogle Drive/Dropboxにアップロード')
    subparsers = parser.add_subparsers(dest='cmd')
    gdrv = subparsers.add_parser('gdrive', help='Google Driveにアップロード')
    gdrv.add_argument('file', help='アップロードするファイル')
    gdrv.add_argument('--folder_id', default=None, help='Google DriveフォルダID')
    dbx = subparsers.add_parser('dropbox', help='Dropboxにアップロード')
    dbx.add_argument('file', help='アップロードするファイル')
    dbx.add_argument('--token', required=True, help='Dropboxアクセストークン')
    dbx.add_argument('--path', required=True, help='Dropbox上の保存パス')
    args = parser.parse_args()
    if args.cmd == 'gdrive':
        upload_to_gdrive(args.file, args.folder_id)
    elif args.cmd == 'dropbox':
        upload_to_dropbox(args.file, args.token, args.path)
    else:
        print('gdrive/dropbox サブコマンドを指定してください')

if __name__ == '__main__':
    main()
