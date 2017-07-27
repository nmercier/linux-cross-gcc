config={}
with open('etc/pkg/config', 'r') as config_file:
    exec(config_file.read(), config)
print('pkg for FreeBSD %s %s' % (config['DIST'], config['ARCHITECTURE'][1]))

import os
import subprocess
import sys
import re
import io
import shutil
import copy
try:
    import urllib2
except ImportError:
    from urllib import request as urllib2
import bz2, lzma
try:
    import cPickle as pickle
except ImportError:
    import pickle
import tarfile

try:
    from hashlib import sha256
except ImportError:
    from sha256 import sha256
import etc.pkg.yaml as yaml

desc="""
pkg {base | -h}
"""


available_package_list_file = 'var/cache/pkg/package_available.pkl'
installed_package_list_file = 'var/cache/pkg/package_installed.pkl'
link_package_list_file = 'var/cache/pkg/package_links.pkl'
db_folder = 'var/cache/pkg'
package_folder = 'var/cache/pkg/archives'


number_re = re.compile('([0-9]+)')


class PkgStringVersion:
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

assert(PkgStringVersion('52~m1-1~') < PkgStringVersion('52.1-3'))


def to_version(version_string):
    result = []
    epoch, __, version = version_string.partition(':')
    if not version:
        version = epoch
        epoch = 0
    else:
        epoch = int(epoch)
    upstream_version, __, pkg_version = version.rpartition('-')
    if not upstream_version:
        upstream_version = pkg_version
        pkg_version = ''

    result.append(epoch)
    result += [int(text) if text.isdigit() else PkgStringVersion(text) for text in number_re.split(upstream_version)]
    result += [int(text) if text.isdigit() else PkgStringVersion(text) for text in number_re.split(pkg_version)]
    return result



class Package:
    KEYS = [
        ('name', ''),
        ('version', ''),
        ('prefix', ''),
        ('repopath', ''),
        ('pkgsize', 0),
        ('flatsize', 0),
        ('deps', {}),
        ('shlibs_required', []),
        ('origin', ''),
        ('sum', ''),
    ]
    def __init__(self, attrs):
        for key, default_value in self.KEYS:
            setattr(self, key, attrs.get(key, default_value))


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

    def __str__(self):
        return '%s:%s [%s]' % (self.package_name, self.package_arch, self.Version)


def usage():
    print(desc)


def do_download(package_list):
    for package in package_list:
        filename = os.path.split(package.repopath)[1]
        filepath = os.path.join(package_folder, filename)
        with open(filepath, 'wb') as f:
            f.write(download(config['PKG_MIRROR'] + '/' + package.repopath))


def filter_packages_to_download(package_list):
    result = []
    for package in package_list:
        filename = os.path.split(package.repopath)[1]
        filepath = os.path.join(package_folder, filename)
        if os.path.isfile(filepath):
            with open(filepath, 'rb') as f:
                m = sha256()
                m.update(f.read())
            if m.hexdigest().lower() == package.sum.lower():
                continue
        result.append(package)
    return result


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


def save_installed_packages(installed_packages):
    with open(installed_package_list_file, 'wb') as installed_packages_db:
        pickle.dump(installed_packages, installed_packages_db)



def do_install(database, package_list):
    for package in package_list:
        print('Unpacking %s...'%package.name)
        links = []
        filename = os.path.split(package.repopath)[1]
        filepath = os.path.join(package_folder, filename)
        dbpath = os.path.join(db_folder, package.name+'+MANIFEST')
        with open(filepath, 'rb') as archive:
            archive = tarfile.open(fileobj=archive)
            manifest = archive.extractfile('+MANIFEST')
            with open(dbpath, 'w') as manifest_file:
                manifest_file.write(manifest.read().decode('utf-8'))
            with open(dbpath, 'r') as manifest_file:
                manifest = yaml.load(manifest_file)
            for member in archive:
                if member.name in ('+MANIFEST', '+COMPACT_MANIFEST'):
                    continue
                if member.name[0] == '/':
                    member.name = member.name[1:]
                if sys.platform == 'win32':
                    member.name = member.name.replace(':', '_')
                if member.isfile():
                    try: os.makedirs(os.path.split(member.name)[0])
                    except OSError: pass
                    with open(member.name, 'wb') as f:
                        f.write(archive.extractfile(member).read())
                elif member.isdir():
                    try: os.makedirs(member.name)
                    except OSError: pass
                elif member.islnk() or member.issym():
                    if sys.platform == 'win32':
                        links.append(member)
                    else:
                        if member.linkname[0] == '/':
                            member.linkname = os.path.relpath('.', os.path.split(member.name)[0]) + member.linkname
                            print(member.name, '  ->  ', member.linkname)
                        try: os.makedirs(os.path.split(member.name)[0])
                        except OSError: pass
                        try:
                            os.symlink(member.linkname, member.name)
                        except OSError:
                            os.unlink(member.name)
                            os.symlink(member.linkname, member.name)
                elif member.isdev():
                    print('Dev node: %s' % member.name)
        links = set(links)
        for l in links:
            if l.linkname[0] == '/':
                l.linkname = l.linkname[1:]
            else:
                l.linkname = os.path.join(os.path.split(l.name)[0], l.linkname)
            if sys.platform == 'win32':
                l.linkname = l.linkname.replace(':', '_')
        while links:
            links_current = set(links)
            removed = 0
            while links_current:
                l = links_current.pop()
                #print ('%s->%s' % (l.name, l.linkname))
                try: os.makedirs(os.path.split(l.name)[0])
                except OSError: pass
                try:
                    with open(l.linkname, 'rb') as target:
                        with open(l.name, 'wb') as link:
                            link.write(target.read())
                except OSError:
                    pass
                else:
                    links.remove(l)
                    removed += 1
            if not removed:
                print('Unable to create links:')
                for l in links:
                    print ('%s->%s' % (l.name, l.linkname))
                continue
        database[package.name] = package
    save_installed_packages(database)


def do_uninstall(database, package_list):
    for p in package_list:
        with open(os.path.join(db_folder, p.name+'+MANIFEST'), 'r') as manifest:
            desc = yaml.load(manifest)
            for file in desc['files'].keys():
                print(file)
                if file[0] == '/':
                    file = file[1:]
                os.unlink(file)
                try: os.removedirs(os.path.split(file)[0])
                except OSError: pass
        del database[p.name]
    save_installed_packages(database)


def uninstall(package_list):
    try:
        with open(installed_package_list_file, 'rb') as file:
            packages_installed = pickle.load(file)
    except OSError:
        packages_installed = {}
    packages_to_remove = []
    for p in package_list:
        try:
            p = packages_installed[p]
        except KeyError:
            print('Coult not locate installed package %s' % p)
            return
        else:
            packages_to_remove.append(p)
    do_uninstall(packages_installed, packages_to_remove)


def install(package_list):
    install_candidates = []
    try:
        with open(installed_package_list_file, 'rb') as file:
            packages_installed = pickle.load(file)
    except OSError:
        packages_installed = {}

    try:
        with open(available_package_list_file, 'rb') as file:
            packages, shlibs = pickle.load(file)
    except OSError:
        print('Run python3 pkg.py update before installing packages')
        return

    for package in package_list:
        deps_seen = set([package])

        package_set = set(package_list)
        seen = set([])
        while package_set:
            package = package_set.pop()
            if package in seen:
                continue
            seen.add(package)
            try:
                p = packages[package]
            except KeyError:
                print('No package %s' % package)
                return
            else:
                install_candidates.append(p)
                package_set = package_set.union(p.deps.keys())
                for shlib_dep in p.shlibs_required:
                    try:
                        offer = shlibs[shlib_dep]
                    except KeyError:
                        print('No shlib %s' % shlib_dep)
                        return
                    else:
                        p = offer[0]
                        if len(offer) > 1:
                            print('[info] selecting package %s to provide shlib %s (candidates: %s)' % (p.name, shlib_dep, ','.join([o.name for o in offer])))
                        if p.name not in seen:
                            seen.add(p.name)
                            install_candidates.append(p)
                            package_set = package_set.union(p.deps.keys())

        to_install = []
        to_update = []
        for p in install_candidates:
            try:
                installed_version = packages_installed[p.name]
            except KeyError:
                p.refcount = 0
                to_install.append(p)
            else:
                if p.version != installed_version.version:
                    to_update.append((installed_version, p))

        if to_install:
            print('The following NEW packages will be installed:\n %s\n' % ', '.join(p.name for p in to_install))
        if to_update:
            print('The following packages will be upgraded:\n %s\n' % ', '.join(p.name for p,_ in to_update))
        print('%d upgraded, %d newly installed, and %d to remove' % (len(to_update), len(to_install), 0))
        download_packages = filter_packages_to_download(to_install + [p for _, p in to_update])
        download_size = float(sum([p.pkgsize for p in download_packages]))
        total_package_size = float(sum([p.pkgsize for p in to_install]))
        total_package_size += float(sum([p.pkgsize for _,p in to_update]))
        install_size = float(sum([p.flatsize for p in to_install]))
        install_size += float(sum([p.flatsize for p,__ in to_update]))
        install_size -= float(sum([p.flatsize for __,p in to_update]))

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
        unit = 'B'
        disk = 'used'
        if install_size < 0:
            disk = 'freed'
            install_size = -install_size
        if install_size > 1024*5:
            install_size /= 1024
            unit = 'kB'
        if install_size > 1024*5:
            install_size /= 1024
            unit = 'MB'
        print('After this operation, %0.2f %s of additional disk space will be %s.' % (install_size, unit, disk))
        print('Do you want to continue? [Y/n]',)

        do_download(download_packages)
        do_uninstall(packages_installed, [p for p,__ in to_update])
        do_install(packages_installed, [p for __,p in to_update])
        do_install(packages_installed, to_install)
        def copy(path, target):
            for f in os.listdir(path):
                p = os.path.join(path, f)
                t = os.path.join(target, f)
                if os.path.isdir(p):
                    copy(p, t)
                else:
                    try: os.makedirs(target)
                    except OSError: pass
                    with open(p, 'rb') as source_file:
                        with open(t, 'wb') as target_file:
                            target_file.write(source_file.read())
        try:
            for d in os.listdir('usr/local/lib'):
                if d[0] == '.':
                    p = os.path.join('usr/local/lib', d)
                    copy(p, 'usr/local/lib')
        except OSError:
            pass
        #save_database(installed_packages, installed_links)
        print('Do you want to delete downloaded packages? [Y/n]',)
        #do_delete_packages(to_install + [p for p, __ in updated_packages])



def update():
    packages = {}
    shlibs = {}
    base_url = config['PKG_MIRROR'] + '/packagesite.txz'
    try:
        data = download(base_url)
    except Exception as e:
        print('could not download %s:\n %s' % (base_url, e))
        return
    tar = tarfile.open(fileobj=io.BytesIO(data))
    for line in  tar.extractfile(tar.getmember('packagesite.yaml')):
        try:
            desc = yaml.load(line.decode('latin1'))
        except UnicodeDecodeError:
            print('invalid UTF8 line: %s' %line)
        except yaml.YAMLError:
            print('malformed YAML package desc: %s' % line)
        else:
            pkg = Package(desc)
            if pkg.name in packages:
                print(pkg.name)
            packages[pkg.name] = pkg
            try:
                shlibs_provided = desc['shlibs_provided']
            except KeyError:
                pass
            else:
                for lib in shlibs_provided:
                    try:
                        shlibs[lib].append(pkg)
                    except KeyError:
                        shlibs[lib] = [pkg]

    directory = os.path.split(available_package_list_file)[0]
    try: os.makedirs(directory)
    except OSError: pass

    directory = os.path.split(installed_package_list_file)[0]
    try: os.makedirs(directory)
    except OSError: pass

    try: os.makedirs(package_folder)
    except OSError: pass

    with open(available_package_list_file, 'wb') as file:
        pickle.dump((packages, shlibs), file)



def base():
    for pkg, required in [
        ('kernel.txz', True),
        ('base.txz', True),
        ('lib32.txz', False),
     ]:
        base_url = config['MIRROR'] + config['ARCHITECTURE'][0] + '/' + config['ARCHITECTURE'][1] + '/' + config['DIST'] + '/' + pkg
        if required or config['ARCHITECTURE'][2]:
            try:
                data = download(base_url)
            except Exception as e:
                if not optional:
                    raise e
            else:
                tar = tarfile.open(fileobj=io.BytesIO(data))
                for tarinfo in tar:
                    tarinfo = copy.copy(tarinfo)
                    tarinfo.mode = 0o700
                    try:
                        if tarinfo.islnk() or tarinfo.issym():
                            if tarinfo.linkname[0] == '/':
                                tarinfo.linkname = os.path.relpath('.', os.path.split(tarinfo.name)[0]) + tarinfo.linkname
                                print(tarinfo.name, '  ->  ', tarinfo.linkname)
                            os.symlink(tarinfo.linkname, tarinfo.name)
                        else:
                            tar.extract(tarinfo, '.', set_attrs=False)
                    except ValueError as e:
                        print(e)
                    except OSError as e:
                        print(tarinfo.name)
                        os.unlink(tarinfo.name)
                        tar.extract(tarinfo, '.', set_attrs=False)

    def fix_links(dir):
        for l in os.listdir(dir):
            p = os.path.join(dir, l)
            if os.path.islink(p):
                target = p
                seen = set([target])
                while os.path.islink(target):
                    real = os.readlink(target)
                    parent = os.path.split(target)[0]
                    if real[0] == '/':
                        target = '.' + real
                    else:
                        target = os.path.join(parent, real)
                    if target in seen:
                        print ('recursive link: %s => %s' % (p, target))
                    seen.add(target)
                if os.path.exists(target):
                    print ('%s => %s' % (p, target))
                    os.unlink(p)
                    if os.path.isdir(target):
                        fix_links(target)
                        shutil.copytree(target, p)
                    else:
                        shutil.copy(target, p)
                else:
                    print('broken link: %s => %s' % (p, target))
                    os.unlink(p)
            elif os.path.isdir(p):
                fix_links(p)
    if sys.platform == 'win32':
        fix_links('.')


if __name__ == '__main__':
    command  = sys.argv[1]
    packages = sys.argv[2:]

    if command == '-h':
        usage()
    elif command == 'base':
        if packages:
            raise Exception(desc)
        base()
    elif command == 'update':
        if packages:
            raise Exception(desc)
        update()
    elif command == 'install':
        install(packages)
    elif command == 'uninstall':
        uninstall(packages)
    else:
        raise Exception('unknown command: %s\n\n%s' % (command, desc))
