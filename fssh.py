#!/usr/bin/env python
#
# fssh - The functional salt shell
#
# Copyright (C) 2015-2016 Eric Webster <sophomeric@gmail.com>
# Portions  (C) 2012-2013 Dennis Kaarsemaker <dennis@kaarsemaker.net>
# see COPYING for license details

# Wishlist:
#   Some option to parse nodegroups.conf instead/additionally
#   Something frequently used/common tasks
#       macros that apply filters and commands for common tasks

# To Do:
# [main] section in config file
# Make available pillars print with ? (if available)
# Print last jid with ? as well (add self.jid)

import ConfigParser
import fcntl
import json
import optparse
import os
#from pprint import pprint
import pwd
import re
import readline
import socket
import struct
import sys
import termios

history_file = '~/.salt_history'

p = optparse.OptionParser(usage="%prog [opts] [scripts]")
p.add_option('-v', '--verbose', dest="verbose", action="store_true", default=False,
             help="Print all commands before executing")
p.add_option('-i', '--interactive', dest="interactive", action="store_true", default=False,
             help="Start an interactive shell after processing all files")
p.add_option('-n', '--noop', dest="noop", action="store_true", default=False,
            help="Don't actually do anything, just show what would be done."
            " Useful for generating CLI commands. Job lookups can still be performed.")
p.add_option('-p','--no-pillars', dest='use_pillars', action="store_false", default=True,
            help="Don't load (or support) pillars."
            " This is useful for faster debugging and troubleshooting fssh itself.")
p.add_option('-c', '--config', dest="config", action="store", default='/etc/fssh.conf',
             help="Config file to use. Default=/etc/fssh.conf")
opts, files = p.parse_args()

if not files or opts.interactive:
    files.append(sys.stdin)

opts.user = os.environ.get('SUDO_USER', pwd.getpwuid(os.getuid()).pw_name)

if os.geteuid() != 0:
    print "Not launched via sudo, fixing that for you."
    os.execvp("sudo", ["sudo"] + sys.argv)

# You might have to be root to even load the libraries
# if people add custom code to create files that get run as root, etc
# so load these after the root check
import salt.client
import salt.runner

def get_columns():
    COLUMNS = 80
    if 'COLUMNS' in os.environ:
        COLUMNS = int(os.environ['COLUMNS'])
    else:
        ROWS, COLUMNS = struct.unpack('hh', fcntl.ioctl(sys.stdin, termios.TIOCGWINSZ, '1234'))
    return COLUMNS

def _padder(tosay = ''):
    print "{0}".format(tosay).center(get_columns(), '-')

def display_filters(list):
    _padder(" Current filters to apply: ")
    for filter in list:
        print " ".join(filter)

def get_salt_filters(list, pillars):
    salt_filters = []
    for filter in list:
        if len(filter) == 2:
            """ Host/PCRE matching """
            if filter[0] == '-':
                salt_filters.append("not E@{0}".format(filter[1]))
            else:
                salt_filters.append("E@{0}".format(filter[1]))
        elif len(filter) == 4:
            """ Pillar matching
                Shirley, this could be more elegant. """

            """ It really might make more sense to change the semantics
                for this entirely. The leading + - are really confusing when
                translated to real logic.

                - state != live | I@state:live
                - state == live | not I@state:live
                + state != live | not I@state:live
                + state == live | I@state:live """

            if filter[0] == '-':
                if filter[2] == '!=':
                    salt_filters.append("I@{0}:{1}".format(filter[1], filter[3]))
                else:
                    salt_filters.append("not I@{0}:{1}".format(filter[1], filter[3]))
            else:
                if filter[2] == '!=':
                    salt_filters.append("not I@{0}:{1}".format(filter[1], filter[3]))
                else:
                    salt_filters.append("I@{0}:{1}".format(filter[1], filter[3]))
        else:
            print >>sys.stderr, "This really shouldn't be possible. Bailing."
            sys.exit(999)
    return " and ".join(salt_filters)

class SaltShell(object):
    def __init__(self, files, opts):
        self.user = opts.user
        self.ps4 = os.environ.get('PS4', '+ ')
        self.files = [hasattr(f, 'readline') and ('-', f, 0) or (f, open(f), 0) for f in files]
        self.filters = []
        self.fqdn = socket.getfqdn()
        self.pillars = {}
        self.config_file = opts.config
        self.config = self.getConfig()
        self.job = ''
        self.salt = salt.client.LocalClient()
        self.runner = salt.runner.RunnerClient(salt.config.master_config('/etc/salt/master'))

    def getConfig(self):
        if os.path.isfile(self.config_file):
            config = ConfigParser.SafeConfigParser()
            config.read(self.config_file)
            return config
        else:
            return False

    def printConfig(self):
        if self.config:
            print "Config loaded from {0}:\n".format(self.config_file)
            for section_name in self.config.sections():
                print "[Section: {0}]:".format(section_name)
                for name, value in self.config.items(section_name):
                    print "  {0} = {1}".format(name, value)
                print

    def run_shell(self):
        do_readline = sys.stdin.isatty() and ('-', sys.stdin, 0) in self.files
        if do_readline and os.path.exists(os.path.expanduser(history_file)):
            readline.read_history_file(os.path.expanduser(history_file))
            for file in ('/etc/inputrc', os.path.expanduser('~/.inputrc')):
                if os.path.exists(file):
                    with open(file) as fd:
                        readline.parse_and_bind(fd.read())

        if opts.verbose:
            self.printConfig()

        if opts.use_pillars:
            """ Load pillars for myself to get a list to display
                as possible options. I copy the data to self to
                preserve types and such, and maybe the example
                data being available will be useful later. """
            print "Loading available pillars.",
            sys.stdout.flush()
            pillars = self.salt.cmd(self.fqdn, 'pillar.raw', [''])
            pillars = pillars[self.fqdn]
            self.pillars = dict(pillars)
            for pillar in pillars:
                if re.match('^graindiff.*$', pillar):
                    del self.pillars[pillar]
            print "   Done!"
            if opts.verbose:
                _padder(" Available pillars and their data types: ")
                for pillar in self.pillars:
                    print "{0} {1}".format(type(self.pillars[pillar]), pillar)
                _padder(" Keep in mind that only str has really been tested. ")

        while self.files:
            self.curfile, self.curfd, self.curline = self.files[0]
            self.files = self.files[1:]
            try:
                while True:
                    line = self.get_input()
                    if not line:
                        break
                    self.parse_and_run(line)

            except:
                if do_readline:
                    readline.write_history_file(os.path.expanduser(history_file))
                raise

        if do_readline:
            readline.write_history_file(os.path.expanduser(history_file))

    def get_input(self):
        while True:
            self.curline += 1
            try:
                if self.curfd.isatty():
                    line = raw_input('fssh> ')
                else:
                    line = self.curfd.readline()
            except KeyboardInterrupt:
                print >>sys.stderr, "KeyboardInterrupt (Use ^D or exit to exit)"
                continue
            except EOFError:
                if self.curfd.isatty():
                    print ""
                break
            if line == '':
                if not self.curfd.isatty():
                    break
            if not line or line.startswith('#'):
                continue

            return line.strip()

    def parse_and_run(self, line):

        """
            More like, parse and then run.
            Parse input and decide what to do.

            . will source a file (?)
            run_task is do something
            run_admin_command is internal stuff, like build lists
                - + = trigger it
                    < read host patterns from file
                You can get into a bad spot with abusing =
                Sure, you can pass in a brazillion host names and it will
                    let you, even accepting the job and returning a job #.
                    But it won't actually do anything beyond some upper
                    character limit. This is the main reason for removing
                    the host list generation in the first place. It's
                    more of a character limit than a host limit, in that
                    at some point it will just fall apart, not at a an exact #.
            ? is show hosts,
                also make it look up jobs if passed a number
            ?? show current job results if set
        """

        line = line.strip()
        if line[0] == '.':
            """ TODO: This code is just grandfathered in.
                I don't really know if anyone uses it. """
            self.files.insert(0, (self.curfile, self.curfd, self.curline))
            self.curfile = line[1:].strip()
            try:
                self.curfd = open(self.curfile)
                self.curline = 0
            except (OSError, IOError) as e:
                print "File {0} not found or unable to open it.".format(line[1:])
                print e
            return
        if line == 'help':
            run_help()
            return
        elif line in ['clear', 'reset']:
            self.filters = []
            self.job = ''
            print "Filters and jobid (if any) have been reset!"
            return
        elif line in ['exit', 'quit']:
            self.run_exit()
            return # lol
        elif line in ['meow']:
            print """
            .                .
            :"-.          .-";
            |:`.`.__..__.'.';|
            || :-"      "-; ||
            :;              :;
            /  .==.    .==.  \\
           :      _.--._      ;
           ; .--.' `--' `.--. :
          :   __;`      ':__   ;
          ;  '  '-._:;_.-'  '  :
          '.       `--'       .'
           ."-._          _.-".
         .'     ""------""     `.
        /`-                    -'\\
       /`-                      -'\\
      :`-   .'              `.   -';
      ;    /                  \    :
     :    :                    ;    ;
     ;    ;                    :    :
     ':_:.'                    '.;_;'
        :_                      _;
        ; "-._                -" :`-.     _.._
        :_          ()          _;   "--::__. `.
         \\"-                  -"/`._           :
        .-"-.                 -"-.  ""--..____.'
       /         .__  __.         \\
      : / ,       / "" \       . \ ; bug
       "-:___..--"      "--..___;-" """
        elif line[0:2] == '??':
            if self.job:
                self.run_query()
            else:
                print "There's no job to lookup."
                return
        elif line[0] == '?':
            return self.run_query_command(line)
        elif line[0] in ['+', '-', '=']:
            command = line.split()

            if len(command) == 4:
                # See if there's a substitution map available in the config file
                # ie, map value to value for common short hand expressions
                command[1] = command[1].lower()

                if self.config:
                    if self.config.has_section('pillar_map'):
                        if self.config.has_option('pillar_map',command[1]):
                            command[1] = self.config.get('pillar_map',command[1])

                """ Only accept things that are actually valid pillars. """
                if len(self.pillars) == 0:
                    if opts.use_pillars:
                        print "No pillars found."
                    else:
                        print "Using pillars was disabled at run time."
                elif command[1] not in self.pillars:
                    print "'{0}' is not a valid pillar to filter by.\nTry one of these:".format(command[1])
                    for pillar in self.pillars:
                        print "{0} {1}".format(type(self.pillars[pillar]), pillar)
                    return

                """ Strip leading and trailing quote characters. """
                if command[3][:1] in ['"', "'"]:
                    command[3] = command[3][1:]
                if command[3][-1:] in ['"', "'"]:
                    command[3] = command[3][0:-1]
            if len(command) in [2, 4]:
                return self.run_admin_command(command)
            else:
                print "Unrecognized command format/input:\n{0}".format(" ".join(command))
                return
        else:
            return self.run_task(line)

    def run_query_command(self, line):
        query = line.split()

        if len(query) == 1:
            """ Translate and display the filters. """
            _padder("~ Current Summary ~")
            if len(self.filters) > 0:
                display_filters(self.filters)
                self.display_cli_guess("<your command here>")
                _padder()
            else:
                print "Nothing! Try adding some filters!"
            return
        elif len(query) == 2:
            if query[1].isdigit():
                """ TODO: Lookup job id here. """
                self.job = query[1]
                self.run_query()
                return
            else:
                print >>sys.stderr, "Invalid input or not a job number (isdigit): {0}".format(query[1])
                return
        else:
            print "Error: Invalid command."
            return

    def run_admin_command(self, line):

        """ This is where you'd do verification of
            such commands. """

        if line[0] == '=':
            """ Discouraged: Here you have told me to run it on a specific host
            via the legacy '= hostspec' format. This will work, but will
            fail on long lists. It's more of a character limit than a host limit
            so it's not really fair to remove it entirely because you can work on
            small sets of hosts. The bad news is that when you hit that limit, 
            everything still *appears* to work. It will submit the job and give
            you a jobid back but nothing will actually be done with it.
            Things started falling apart somewhere between 1,000 and 2,000 hosts.
            """
            line[0] = '+'

        if len(line) == 2:
            if line[0] == '<':
                fname = line[1:]
                """ TODO: This probably doesn't work,
                    and what it should be doing likely doesn't
                    belong in this part of the application. """
                if not os.path.exists(fname):
                    print "No such file: {0}".format(fname)
                    return set()
                with open(fname) as fd:
                    query = ';'.join(set([x.strip() for x in fd.read().strip().splitlines()]))
            if line[1] == '.*':
                _padder(" ! Hey there meow ! ")
                _padder()
                print "You just told me to match every host,"
                print "so here's a big warning on your screen to make sure"
                print "that's what you intended!"
                _padder()
                _padder()

        elif len(line) == 4:

            attr, op, val = line[1:]
            matched = []
            if op not in ['==','!=']:
                print "Err: {0} is not a valid comparision option.".format(op)

        else:
            raise Exception, "Unsupported query/command." "Got: {0}".format(line)

        self.filters.append(line)
        return

    def run_query(self):
        return self.run('runner', 'jobs.lookup_jid', [ self.job ])

    def run_task(self, line):
        command = line.strip()

        """ Some logic to detect modules and their args here?
            Run those instead, cmd.shell otherwise.
            if re.match('^[a-zA-Z0-9]+\.[a-zA-Z0-9]+\(\\'.*\\'\)$' .... """
        return self.run('salt', 'cmd.shell', [self.user, line])

    def run_exit(self):
        raise SystemExit()

    def run(self, method, module, args):

        if method == 'salt' and len(self.filters) == 0:
            print >>sys.stderr, "Cannot run command on 0 hosts. And some filters!"
            return

        try:
            if method == 'runner':
                self.runner.cmd(module, args)
                return
            elif method == 'salt':
                if os.getuid() != 0:
                    """ Should do this check earlier. """
                    print >>sys.stderr, os.getuid()
                    print >>sys.stderr, "Can not run commands as a normal user."
                    sys.exit(7)

                # Returns 0 on failure otherwise job id
                if not opts.noop:
                    job = self.salt.cmd_async(get_salt_filters(self.filters, self.pillars), module, [ args[1] ], expr_form='compound')
                    if opts.verbose:
                        self.display_cli_guess(args[1])
                        print "Job status: {0}".format(job)
                        _padder()
                    if job != 0:
                        self.job = job
                        print "Job submitted successfully: {0}".format(job)
                    else:
                        print "There was an error executing your job!"
                else:
                    print "- In noop mode. Here's what I would be doing -"
                    self.display_cli_guess(args[1])
                return
            else:
                print >>sys.stderr, "(Currently) Unsupported method: {0}\nGoodbye.".format(method)
                sys.exit(5)

        except KeyboardInterrupt:
            print >>sys.stderr, "KeyboardInterrupt."
            return
        except Exception:
            print >>sys.stderr, wrap("Couldn't process command", attr.bright, fgcolor.red)
            import traceback
            traceback.print_exc()
            return

    def display_cli_guess(self, command, interface = 'salt', module = 'cmd.shell'):
        _padder(" CLI equivalent ")
        print "sudo {0} --async -C '{1}' {2} '{3}'".format(interface, get_salt_filters(self.filters, self.pillars), module, command)

class Attr(object):
    def __init__(self, **attr):
        for k, v in attr.items():
            setattr(self, k, v)

def run_help():
    print """Functional Salt SHell 0.5.76.Does It Matter?

Query commands:
   ? [jobid]    Displays current settings.
                If the optional jobid is supplied, look up that job number.
  ??            Look up the results of the most recently run, or looked up job.

Targeting/Filtering commands:
   + hostspec   Include this spec as a target.
   - hostspec   Exclude this spec as a target.
   = hostspec   Sets the hosts to use. This is discouraged.
                If you'd like to know why, look for that word in the source.

   hostspecs should be PCRE compatible regexes. They need to match the
   *entire* hostname you wish to target. So '.*fe-web.*' not 'fe-web'. They
   are passed directly to salt and it requires this.

Complex Targeting/Filtering:
    (+|-) field (!=|==) value
    The same concepts as basic filtering, but targeting based on
    pillar data. Example:

    + status == live    | Include any hosts whose status is live.
    - env != production | Don't include a host whose environment is not production.

    For a list of available pillars, try matching on one that doesn't exist!
    Note that running ? after adding some filters will show you the equivalent
    salt CLI command, and that might make more sense logically when you see that.

    This magic depends on the magic of external pillars.

Special commands:
    clear   Reset your fssh environment, clears any existing filters and jobid
    reset   Same as clear.

Running shell commands (basically anything else):

   command arg1 arg2 arg3
"""

fgcolor = Attr(black=30, red=31, green=32, yellow=33, blue=34, magenta=35, cyan=36, white=37, none=None)
bgcolor = Attr(black=40, red=41, green=42, yellow=43, blue=44, magenta=45, cyan=46, white=47, none=None)
attr    = Attr(normal=0, bright=1, faint=2, underline=4, negative=7, conceal=8, crossed=9, none=None)

esc = '\033'
mode = lambda *args: "%s[%sm" % (esc, ';'.join([str(x) for x in args if x is not None]))
reset = mode(attr.normal)
wrap = lambda text, *args: sys.stdout.isatty() and "%s%s%s" % (mode(*args), text, reset) or text

if __name__ == '__main__':
    SaltShell(files, opts).run_shell()
