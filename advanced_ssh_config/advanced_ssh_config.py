# -*- coding: utf-8 -*-

import os
import ConfigParser
import re
import subprocess
import logging
import errno


class AdvancedSshConfig(object):

    def __init__(self, hostname=None, port=22, configfile=None, verbose=False,
                 update_sshconfig=False, dry_run=False):

        self.verbose, self.dry_run = verbose, dry_run
        self.hostname, self.port = hostname, port

        self.log = logging.getLogger('')

        self.configfiles = [
            '/etc/ssh/config.advanced',
            os.path.expanduser('~/.ssh/config.advanced')
            ]
        if configfile:
            self.configfiles += configfile
        self.parser = ConfigParser.ConfigParser()
        self.parser.SECTCRE = re.compile(
            r'\['
            r'(?P<header>.+)'
            r'\]'
            )

        errors = 0
        self.parser.read(self.configfiles)
        includes = self.conf_get('includes', 'default', '').strip()
        for include in includes.split():
            incpath = os.path.expanduser(include)
            if not incpath in self.configfiles and os.path.exists(incpath):
                self.parser.read(incpath)
            else:
                self.log.error('\'%s\' include not found' % incpath)
                errors += 1

        if 0 == errors:
            self.debug()
            self.debug('configfiles : %s' % self.configfiles)
            self.debug('================')
        else:
            raise ConfigError('Errors found in config')

        if update_sshconfig:
            self._update_sshconfig()

    def debug(self, string=None):
        self.log.debug(string and string or '')

    def conf_get(self, key, host, default=None, vardct=None):
        for section in self.parser.sections():
            if re.match(section, host):
                if self.parser.has_option(section, key):
                    return self.parser.get(section, key, False, vardct)
        if self.parser.has_option('default', key):
            return self.parser.get('default', key)
        return default

    def _get_controlpath_dir(self, hostname):
        controlpath = self.conf_get('controlpath', 'default', '/tmp')
        dir = os.path.dirname(os.path.expanduser(controlpath))
        dir = os.path.join(dir, self.hostname)
        dir = os.path.dirname(dir)
        return dir

    def _prepare_controlpath(self):
        controlpath_dir = self._get_controlpath_dir(self.hostname)
        try:
            os.makedirs(controlpath_dir)
        except OSError as exception:
            if exception.errno != errno.EEXIST:
                raise exception

    def connect(self):
        # Handle special settings

        self._prepare_controlpath()

        section = None
        for sect in self.parser.sections():
            if re.match(sect, self.hostname):
                section = sect

        self.log.debug('section \'%s\' ' % section)

        # Parse special routing
        path = self.hostname.split('/')

        args = {}
        options = {
            'p': 'Port',
            'l': 'User',
            'h': 'Hostname',
            'i': 'IdentityFile'
            }
        default_options = {
            'p': str(self.port),
            'h': path[0]
            }
        updated = False
        for key in options:
            cfval = self.conf_get(options[key], path[0], default_options.get(key))
            value = self._interpolate(cfval)
            if cfval != value:
                updated = True
                self.parser.set(section, options[key], value)
                args[key] = value

            self.debug('get (-%-1s) %-12s : %s' % (key, options[key], value))
            if value:
                args[key] = value

        # If we interpolated any keys
        if updated:
            self._update_sshconfig()
            self.log.debug('Config updated. Need to restart SSH!?')

        self.debug('args: %s' % args)
        self.debug()

        self.debug('hostname    : %s' % self.hostname)
        self.debug('port        : %s' % self.port)
        self.debug('path        : %s' % path)
        self.debug('path[0]     : %s' % path[0])
        self.debug('path[1:]    : %s' % path[1:])
        self.debug('args        : %s' % args)

        self.debug()
        gateways = self.conf_get('Gateways', path[-1], 'direct').strip().split(' ')
        reallocalcommand = self.conf_get('RealLocalCommand', path[-1], '').strip().split(' ')
        self.debug('reallocalcommand: %s' % reallocalcommand)
        self.debug('gateways    : %s' % ', '.join(gateways))

        for gateway in gateways:
            right_path = path[1:]
            if gateway != 'direct':
                right_path += [gateway]
            cmd = []
            if len(right_path):
                cmd += ['ssh', '/'.join(right_path)]

            cmd += ['nc', args['h'], args['p']]

            self.debug('cmd         : %s' % cmd)
            self.debug('================')
            self.debug()

            if not self.dry_run:
                ssh_process = subprocess.Popen(cmd)
                reallocalcommand_process = None
                if len(reallocalcommand[0]):
                    reallocalcommand_process = subprocess.Popen(reallocalcommand)
                if ssh_process.wait() != 0:
                    self.log.critical('There were some errors')
                if reallocalcommand_process is not None:
                    reallocalcommand_process.kill()

    def _update_sshconfig(self, write=True):
        config = []

        for section in self.parser.sections():
            if section != 'default':
                host = section
                host = re.sub(r'\.\*', '*', host)
                host = re.sub(r'\\\.', '.', host)
                config += ['Host %s' % host]
                special_keys = (
                    'hostname',
                    'gateways',
                    'reallocalcommand',
                    'remotecommand'
                    )
                items = self.parser.items(section, False, {'Hostname': host})
                for key, value in items:
                    if key not in special_keys:
                        if key == 'alias':
                            key = 'hostname'
                        config += ['  %s %s' % (key, value)]
                config += ['']

        config += ['Host *']
        for key, value in self.parser.items('default'):
            if key not in ('hostname', 'gateways', 'includes'):
                config += ['  %s %s' % (key, value)]

        if write:
            fhandle = open(os.path.expanduser('~/.ssh/config'), 'w+')
            fhandle.write('\n'.join(config))
            fhandle.close()
        else:
            print '\n'.join(config)

    def _interpolate(self, value):
        matches = value and re.match(r'\$(\w+)', value) or None
        if matches:
            var = matches.group(1)
            val = os.environ.get(var)
            if val:
                self.log.debug('\'%s\' => \'%s\'' % (value, val))
                return self._interpolate(re.sub(r'\$%s' % var, val, value))

        return value