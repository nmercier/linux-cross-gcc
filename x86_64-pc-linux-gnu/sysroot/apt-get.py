config={}
with open('etc/apt/config', 'r') as config_file:
    exec(config_file.read(), config)

import os
import subprocess
import sys
import re
import io
import shutil
try:
    import urllib2
except ImportError:
    from urllib import request as urllib2
import bz2
try:
    import cPickle as pickle
except ImportError:
    import pickle
import tarfile

try:
    from hashlib import md5
except ImportError:
    from md5 import md5

desc="""
apt-get {update | upgrade | install pkg ...  | remove pkg... | purge pkg... | -h}
"""


available_package_list_file = 'var/cache/apt/package_available.pkl'
installed_package_list_file = 'var/cache/apt/package_installed.pkl'
link_package_list_file = 'var/cache/apt/package_links.pkl'
package_folder = 'var/cache/apt/archives'

number_re = re.compile('([0-9]+)')


class DebianStringVersion:
    def __init__(self, text):
        self.text = text
    def __cmp__(self, other):
        i = 0
        for i in range(0, min(len(self.text), len(other.text))):
            if self.text[i] != other.text[i]:
                if self.text[i] == '~':
                    return -1
                elif other.text[i] == '~':
                    return 1
                elif self.text[i] in ['-', '.', ':']:
                    if other.text[i] in ['-', '.', ':']:
                        return ord(self.text[i]) - ord(other.text[i])
                    else:
                        return -1
                else:
                    if other.text[i] in ['-', '.', ':']:
                        return 1
                    else:
                        return ord(self.text[i]) - ord(other.text[i])
        if len(self.text) > len(other.text):
            if self.text[i] == '~':
                return -1
            else:
                return 1
        else:
            if other.text[i] == '~':
                return 1
            else:
                return -1
    def __eq__(self, other):
        return self.text == other.text
    def __neq__(self, other):
        return self.text == other.text
    def __lt__(self, other):
        return self.__cmp__(other) < 0
    def __le__(self, other):
        return self.__cmp__(other) <= 0
    def __gt__(self, other):
        return self.__cmp__(other) > 0
    def __gt__(self, other):
        return self.__cmp__(other) >= 0

assert(DebianStringVersion('52~m1-1~') < DebianStringVersion('52.1-3'))


def to_version(version_string):
    result = []
    epoch, __, version = version_string.partition(':')
    if not version:
        version = epoch
        epoch = 0
    else:
        epoch = int(epoch)
    upstream_version, __, debian_version = version.rpartition('-')
    if not upstream_version:
        upstream_version = debian_version
        debian_version = ''

    result.append(epoch)
    result += [int(text) if text.isdigit() else DebianStringVersion(text) for text in number_re.split(upstream_version)]
    result += [int(text) if text.isdigit() else DebianStringVersion(text) for text in number_re.split(debian_version)]
    return result



class Package:
    def __init__(self, package_name, package_arch):
        self.package_name = package_name
        self.package_arch = package_arch
        self.Depends = ''
        setattr(self, 'Pre-Depends', '')
        self.filename = ''

    def compatible(self, version_check):
        if version_check:
            assert(version_check[0] == '(')
            assert(version_check[-1] == ')')
            op, version = version_check[1:-1].split(' ')

            version = to_version(version)
            my_version = to_version(self.Version)
            if op == '<<':
                return my_version < version
            if op == '>>':
                return my_version > version
            if op == '=':
                return my_version == version
            if op == '<=':
                return my_version <= version
            if op == '>=':
                return my_version >= version
            raise Exception('unknown op: %s' % op)
        else:
            return True


def generate_ld_conf():
    with open('etc/ld.so.conf', 'w') as ld_so_conf:
        try:
            confs = os.listdir('etc/ld.so.conf.d')
        except OSError:
            pass
        else:
            for conf in confs:
                with open('etc/ld.so.conf.d/%s'%conf) as conf_file:
                    ld_so_conf.write(conf_file.read())
                    ld_so_conf.write('\n')


def usage():
    print(desc)


def download(url):
    def chunk_report(bytes_so_far, chunk_size, total_size):
        if total_size:
            percent = float(bytes_so_far) / total_size
            percent = round(percent*100, 2)
            sys.stdout.write('\r[%0.2f%%] %s...'%(percent, url))
            sys.stdout.flush()
        else:
            data_so_far = float(bytes_so_far)
            unit = 'B'
            if data_so_far > 1024*5:
                data_so_far = data_so_far / 1024
                unit = 'kB'
            if data_so_far > 1024*5:
                data_so_far = data_so_far / 1024
                unit = 'MB'
            sys.stdout.write('\r[%0.2f%s] %s...'%(data_so_far, unit, url))
            sys.stdout.flush()
    chunk_size = 8192
    data = bytes()
    response = urllib2.urlopen(url)
    try:
        total_size = response.info()['Content-length'].strip()
        total_size = int(total_size)
    except Exception as e:
        print(e)
        total_size = 0
    bytes_so_far = 0
    chunk_report(bytes_so_far, chunk_size, total_size)
    while(1):
        try:
            chunk = response.read(chunk_size)
            bytes_so_far += len(chunk)
            if not chunk:
                break
            data += chunk
            chunk_report(bytes_so_far, chunk_size, total_size)
        except Exception as e:
            print(e)
            return None
    print('')
    return data


def run(*command):
    p = subprocess.Popen(command, stdin = subprocess.PIPE, stdout = subprocess.PIPE, stderr = subprocess.PIPE)
    out, err = p.communicate()
    if p.returncode != 0:
        if not isinstance(err, str):
            err = err.decode('utf-8')
        raise Exception(err)
    return out


def load_database():
    try:
        with open(available_package_list_file, 'rb') as package_file:
            available_packages = pickle.load(package_file)
    except Exception:
        raise Exception('No package database stored\n\n%s' % desc)
    try:
        with open(installed_package_list_file, 'rb') as package_file:
            installed_packages = pickle.load(package_file)
    except Exception:
        installed_packages = {}
        for arch in config['ARCHITECTURES']:
            installed_packages[arch] = {}
    try:
        with open(link_package_list_file, 'rb') as link_file:
            installed_links = pickle.load(link_file)
    except Exception:
        installed_links = []
    return available_packages, installed_packages, installed_links


def save_database(installed_packages, installed_links):
    with open(installed_package_list_file, 'wb') as package_file:
        pickle.dump(installed_packages, package_file)
    with open(link_package_list_file, 'wb') as link_file:
        pickle.dump(installed_links, link_file)


def ensure_directories_exist():
    directory = os.path.split(available_package_list_file)[0]
    try: os.makedirs(directory)
    except OSError: pass

    directory = os.path.split(installed_package_list_file)[0]
    try: os.makedirs(directory)
    except OSError: pass

    try: os.makedirs(package_folder)
    except OSError: pass

    try: os.makedirs('etc')
    except OSError: pass


def filter_packages_to_download(package_list):
    result = []
    for package in package_list:
        filename = os.path.split(package.Filename)[1]
        filepath = os.path.join(package_folder, filename)
        if os.path.isfile(filepath):
            with open(filepath, 'rb') as f:
                m = md5()
                m.update(f.read())
            if m.hexdigest().lower() == package.MD5sum.lower():
                continue
        result.append(package)
    return result


def do_download(package_list):
    for package in package_list:
        filename = os.path.split(package.Filename)[1]
        filepath = os.path.join(package_folder, filename)
        with open(filepath, 'wb') as f:
            f.write(download(config['MIRROR'] + '/' + package.Filename))


def do_delete_packages(package_list):
    for package in package_list:
        filename = os.path.split(package.Filename)[1]
        filepath = os.path.join(package_folder, filename)
        os.remove(filepath)


def do_install(package_list, directory_links):
    links = []
    def read_file(bytes, offset):
        if offset & 1 == 1:
            offset+=1
        filename = bytes[offset:offset+16].decode('latin1').strip()
        filesize = int(bytes[offset+48:offset+58].decode('latin1').strip())
        return offset+60+filesize, filename, bytes[offset+60:offset+60+filesize]
    for package in package_list[::-1]:
        filename = os.path.split(package.Filename)[1]
        filepath = os.path.join(package_folder, filename)
        print(filename)
        package.installed_files = []
        package.installed_dirs = []
        with open(filepath, 'rb') as archive:
            bytes = archive.read()
            i = 8
            i, filename, data = read_file(bytes, i)
            assert(filename == 'debian-binary')
            while i < len(bytes)-1:
                i, filename, data = read_file(bytes, i)
                if filename.startswith('data.tar'):
                    tar = tarfile.open(fileobj=io.BytesIO(data))
                    for info in tar.getmembers():
                        if info.isdir():
                            package.installed_dirs.append(info.name)
                            try:
                                os.mkdir(info.name)
                            except OSError:
                                pass
                        elif info.isfile():
                            filename = info.name
                            if filename[0] == '/':
                                filename = '.'+filename
                            with open(filename, 'wb') as file:
                                file.write(tar.extractfile(info).read())
                            package.installed_files.append(filename)
                        elif info.islnk() or info.issym():
                            links.append((package, info.name, info.linkname))
                        else:
                            print (info.name)
    while links:
        old_links = links
        links = []
        for package, link_path, link_target in old_links:
            if link_target[0] == '/':
                relative_link_target = '.' + link_target
            else:
                relative_link_target = os.path.join(os.path.split(link_path)[0], link_target)
            if os.path.isdir(relative_link_target):
                package.installed_dirs.append(link_path)
                directory_links.append((link_path, relative_link_target))
            elif os.path.isfile(relative_link_target):
                package.installed_files.append(link_path)
                with open(relative_link_target, 'rb') as source:
                    with open(link_path, 'wb') as dest:
                        dest.write(source.read())
            else:
                links.append((package, link_path, link_target))
        if len(old_links) == len(links):
            print("Can't create links:\n " + '\n '.join('%s -> %s' % l for l in links))
            break
    for link_path, link_target in directory_links:
        try:
            shutil.rmtree(link_path)
        except FileNotFoundError:
            pass
        shutil.copytree(link_target, link_path)


def do_uninstall(package_list):
    pass


def update():
    ensure_directories_exist()
    packages = {}
    mirror = config['MIRROR']
    dist = config['DIST']
    package_count = 0
    package = None
    for architecture in config['ARCHITECTURES']:
        packages[architecture] = {}
        for repository in config['REPOSITORIES']:
            url = '%s/dists/%s/%s/binary-%s/Packages.bz2'%(mirror, dist, repository, architecture)
            package_compressed = download(url)
            package_data = bz2.decompress(package_compressed)
            try:
                package_data = package_data.decode('latin1')
            except Exception:
                pass
            for line in package_data.split('\n'):
                if line:
                    split = line.find(':')
                    key = line[:split]
                    value = line[split + 1:].strip()
                if key == 'Package':
                    package = Package(value, architecture)
                    package_count += 1
                    try:
                        packages[architecture][value].append(package)
                    except KeyError:
                        packages[architecture][value] = [package]
                else:
                    setattr(package, key, value)
                    if key == 'Provides':
                        provides = value.split(',')
                        for p in provides:
                            p = p.strip()
                            try:
                                packages[architecture][p].append(package)
                            except:
                                packages[architecture][p] = [package]
    with open(available_package_list_file, 'wb') as package_file:
        pickle.dump(packages, package_file)
    print('Information on %d packages' % package_count)


def upgrade():
    return


def install(package_list):
    available_packages, installed_packages, installed_links = load_database()
    default_architecture = config['ARCHITECTURES'][0]

    package_list = [(p, None) for p in package_list]
    packages_to_check = []
    seen = set([])
    while package_list:
        package_name_arch, package_version = package_list.pop(0)
        arch_start = package_name_arch.find(':')
        if arch_start != -1:
            arch = package_name_arch[arch_start+1:]
            package_name = package_name_arch[:arch_start]
        else:
            arch = default_architecture
            package_name = package_name_arch

        if (package_name, arch) in seen:
            continue
        seen.add((package_name, arch))

        try:
            available_list = sorted(available_packages[arch][package_name], reverse=True, key=lambda x: x.Version.split('-'))
            for package in available_list:
                if package.compatible(package_version):
                    break
            else:
                raise Exception('package %s[%s] version %s has no installed candidates.\n  Available:\n    %s'
                    % (package_name, arch, package_version, '\n    '.join(['%s (%s)'%(p.package_name, p.Version) for p in available_list])))
            packages_to_check.append(package)
            dependencies = package.Depends.split(',') if package.Depends else []
            dependencies += getattr(package, 'Pre-Depends', '').split(',') if getattr(package, 'Pre-Depends', '') else []
            for depend in dependencies:
                depend_choice = depend.split('|')
                for depend in depend_choice:
                    depend = depend.strip().split(' ', 1)
                    depend_name = depend[0]
                    depend_version = depend[1] if len(depend) == 2 else None

                    if (depend_name, arch) in seen:
                        for p in packages_to_check:
                            if p.package_name == depend_name and p.package_arch == arch:
                                if not p.compatible(depend_version):
                                    raise Exception('%s[%s] requires %s[%s] version %s, but version %s is to be installed'
                                        % (package_name, arch, depend_name, arch, depend_version, p.Version))
                        break
                    else:
                        for pname, pver in package_list:
                            if pname == depend_name:
                                break
                else:
                    depend = depend_choice[0].strip().split(' ', 1)
                    depend_name = depend[0]
                    depend_version = depend[1] if len(depend) == 2 else None
                    package_list.insert(0, ('%s:%s'%(depend_name, arch), depend_version))
        except KeyError:
            raise Exception('Unable to locate package %s[%s]'%(package_name, arch))

    new_packages = []
    updated_packages = []
    for package in packages_to_check:
        try:
            installed_package = installed_packages[package.package_arch][package.package_name]
        except KeyError:
            new_packages.append(package)
        else:
            if to_version(package.Version) > to_version(installed_package.Version):
                updated_packages.append((package, installed_package))
    if new_packages:
        print('The following NEW packages will be installed:\n %s\n' % ', '.join(['%s[%s]'%(p.package_name,p.package_arch) for p in new_packages]))
    if updated_packages:
        print('The following packages will be upgraded:\n %s\n' % ', '.join(['%s[%s]'%(p.package_name,p.package_arch) for p,__ in updated_packages]))
    print('%d upgraded, %d newly installed, and %d to remove' % (len(updated_packages), len(new_packages), 0))
    download_packages = filter_packages_to_download(new_packages + [p for p, __ in updated_packages])
    download_size = float(sum([int(p.Size) for p in download_packages]))
    total_package_size = float(sum([int(p.Size) for p in new_packages]))
    total_package_size += float(sum([int(p.Size) for p in new_packages]))
    install_size = float(sum([int(getattr(p, 'Installed-Size')) for p in new_packages]))
    install_size += float(sum([int(getattr(p, 'Installed-Size')) for p,__ in updated_packages]))
    install_size -= float(sum([int(getattr(p, 'Installed-Size')) for __,p in updated_packages]))

    unit_dl = 'B'
    if download_size > 1024*5:
        download_size /= 1024
        unit_dl = 'kB'
    if download_size > 1024*5:
        download_size /= 1024
        unit_dl = 'MB'
    unit = 'B'
    if total_package_size > 1024*5:
        total_package_size /= 1024
        unit = 'kB'
    if total_package_size > 1024*5:
        total_package_size /= 1024
        unit = 'MB'
    print('Need to get %0.2f %s/%0.2f %s of archives.' % (download_size, unit_dl, total_package_size, unit))
    unit = 'kB'
    disk = 'used'
    if install_size < 0:
        disk = 'freed'
        install_size = -install_size
    if install_size > 1024*5:
        install_size /= 1024
        unit = 'MB'    
    print('After this operation, %0.2f %s of additional disk space will be %s.' % (install_size, unit, disk))
    print('Do you want to continue? [Y/n]',) 

    do_download(download_packages)
    do_uninstall([p for __,p in updated_packages])
    do_install([p for p,__ in updated_packages], installed_links)
    do_install(new_packages, installed_links)
    generate_ld_conf()
    save_database(installed_packages, installed_links)
    print('Do you want to delete downloaded packages? [Y/n]',)
    #do_delete_packages(new_packages + [p for p, __ in updated_packages])


def uninstall(package_list):
    return 0


if __name__ == '__main__':
    command  = sys.argv[1]
    packages = sys.argv[2:]

    try:
        if command == '-h':
            usage()
        elif command == 'update':
            if packages:
                raise Exception(desc)
            update()
        elif command == 'upgrade':
            if packages:
                raise Exception(desc)
            upgrade()
        elif command == 'install':
            if not packages:
                raise Exception(desc)
            install(packages)
        elif command == 'remove':
            if not packages:
                raise Exception(desc)
            uninstall(packages)
        elif command == 'purge':
            if not packages:
                raise Exception(desc)
            uninstall(packages)
        else:
            raise Exception('unknown command: %s\n\n%s' % (command, desc))
    except Exception as e:
        print(e.__class__, e)
        exit(1)
    else:
        exit(0)
