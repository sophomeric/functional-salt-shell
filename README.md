fssh - functional salt shell
====================

This is a fork, of sorts, of func-shell and I couldn't think of a better name.

See: https://github.com/seveas/func-shell

The conceptually work the same way, although func and salt are very different.
The idea was to provide a familiar interface to users of func-shell in moving
to salt. Some features were not ported, and some were added.

Installing
----------
All needed modules are included with Python. Salt is only compatible
with Python 2.x and this is written with that in mind. It also is only
useful as is with salt 2015.5.x+ since it uses the cmd.shell module.

It's up to you where you place it, in your PATH or not. Compile the C
file and put the resulting binary and fssh.py in the same location.

Example
-------
fssh has been built to make working with salt a lot easier. It is basically
just a very fancy command line builder but it makes doing things much faster.
For now it is essentially a wrapper for cmd.shell

https://docs.saltstack.com/en/latest/ref/modules/all/salt.modules.cmdmod.html#module-salt.modules.cmdmod.shell

As you work with it and add filters/hostspecs, you can use '?' to see what the
CLI equivalent would be. What really makes this useful is when you tie in
external pillar data to it. Such as, if you have a CMDB you can query/dump
via an external pillar, you can do fancy things like run some commands on
only hosts that have a role of 'webserver' that are in your 'staging'
environment by doing something like this:

    Where 'role' and 'env' are valid fields exposed in your pillars:
    fssh> + role == webserver
    fssh> + env == staging
    fssh> cat /proc/loadavg
    # Job submitted to salt here, it will return a jid
    fssh> ??
    # Short-hand for retrieving the results of the most recently submitted jid

    # Special characters are correctly passed to the target machines
    # so fancier things like this work:

    Restart apache on all of your front end webservers in Europe except those 
    in the berlin4 datacenter (again, all that is up to your pillars):
    fssh> + role == fe_web_server
    fssh> + region == europe
    fssh> - datacenter == berlin4
    fssh> if [[ $(awk '{ printf "%.0f",$2 }' /proc/loadavg) -gt 20 ]]; then service httpd restart; fi
    fssh> ??

https://docs.saltstack.com/en/latest/topics/development/external_pillars.html

Reading the 'help' in fssh will be useful as well. I'll include it as the
next section for convenience as it will likely make this make more sense.

Help
--------------------
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

Configuration File
---------------------
There is support for using a configuration files to make your external pillars
easier to remember. For example, maybe the data source you use for your pillars
has things named in strange ways or you just prefer to use words that make more
sense to humans or that require less typing. If you expose a pillar with a key
called 'environment', maybe you don't want to type that all the time. You can
make a mapping of custom keywords to their datasource meanings and fssh will
understand them from the config file you give it.

Here's an example configuration file:
[pillar_map]
site = building
env = environment
status = state
role = service
dc = location

The left side are things you want to use in fssh
and the right side is what they would actually be called in your pillars.

Sourcing another file
---------------------
Like regular shells, you can source another file with the `.` command:

    . more_commands.fsh

