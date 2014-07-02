#coding:utf-8
__author__ = 'lufeng4828@163.com'

import os
import sys
import logger
import logging
import optparse
from swall.utils import c, \
    daemonize, \
    parse_args_and_kwargs, \
    color, \
    sort_ret, \
    kill_daemon, \
    load_config, \
    set_pidfile

from swall.agent import Agent
from swall.keeper import Keeper
from swall.job import Job


def agent_config(path):
    """
    读取配置文件，返回配置信息
    @param path string:配置文件
    @return dict:
    """
    opts = {
        "swall":
            {
                "node_role": "server",
                "node_ip": "localhost",
                "cache": "var/cache",
                "backup": "var/backup",
                "fs_plugin": "plugins/fservice",
                "pidfile": "/tmp/.swall.pid",
                "log_file": "var/logs/swall.log",
                "log_level": "INFO",
                "token": "yhIC7oenuJDpBxqyP3GSHn7mgQThRHtOnNNwqpJnyPVhR1n9Y9Q+/T3PJfjYCZdiGRrX03CM+VI=",
                "thread_num": 20
            },
        "zk":
            {
                "zk_servers": "localhost:2181",
                "zk_scheme": "digest",
                "zk_auth": "swall!@#",
                "root": "/swall",
                "nodes": "/swall/nodes"
            },
        "fs":
            {
                "fs_type": "rsync",
                "fs_host": "localhost",
                "fs_port": 873,
                "fs_user": "swall",
                "fs_pass": "vGjeVUxxxrrrx8CcZ",
                "fs_tmp_dir": "/data/swall_fs"
            }
    }

    opt = load_config(path)
    ret_opts = opts[os.path.basename(path).rstrip(".conf")]
    ret_opts.update(opt)
    return ret_opts


class OptionParserMeta(type):
    def __new__(cls, name, bases, attrs):
        instance = super(OptionParserMeta, cls).__new__(cls, name, bases, attrs)
        if not hasattr(instance, '_mixin_setup_funcs'):
            instance._mixin_setup_funcs = []
        if not hasattr(instance, '_mixin_process_funcs'):
            instance._mixin_process_funcs = []

        for base in bases + (instance,):
            func = getattr(base, '_mixin_setup', None)
            if func is not None and func not in instance._mixin_setup_funcs:
                instance._mixin_setup_funcs.append(func)

        return instance


class BaseOptionParser(optparse.OptionParser, object):
    usage = '%prog [OPTIONS] COMMAND [arg...]'
    description = None
    version = None

    def __init__(self, *args, **kwargs):
        if self.version:
            kwargs.setdefault('version', self.version)

        kwargs.setdefault('usage', self.usage)

        if self.description:
            kwargs.setdefault('description', self.description)

        optparse.OptionParser.__init__(self, *args, **kwargs)

    def parse_args(self, args=None, values=None):
        options, args = optparse.OptionParser.parse_args(self, args, values)
        self.options, self.args = options, args
        return options, args

    def _populate_option_list(self, option_list, add_help=True):
        optparse.OptionParser._populate_option_list(
            self, option_list, add_help=add_help
        )
        for mixin_setup_func in self._mixin_setup_funcs:
            mixin_setup_func(self)

    def print_help(self, file=None):
        """
        overwrite the print_help
        """
        if file is None:
            file = sys.stdout
        result = []
        if self.usage:
            result.append(self.get_usage() + "\n")
        if self.description:
            result.append(self.description)
        result.append(self.format_option_help(self.formatter))

        encoding = self._get_encoding(file)
        file.write("%s\n" % "".join(result).encode(encoding, "replace"))


class ConfParser(BaseOptionParser):
    def setup_config(self):
        opts = {f: agent_config(self.get_config_file_path("%s.conf" % f))
                for f in ('swall', 'zk', 'fs')}
        return opts

    def __merge_config_with_cli(self, *args):
        for option in self.option_list:
            if option.dest is None:
                continue
            value = getattr(self.options, option.dest)
            if option.dest not in self.config["swall"]:
                if value is not None:
                    self.config["swall"][option.dest] = value
            elif value is not None and value != self.config["swall"][option.dest]:
                self.config["swall"][option.dest] = value

        for group in self.option_groups:
            for option in group.option_list:
                if option.dest is None:
                    continue
                value = getattr(self.options, option.dest)
                if option.dest not in self.config["swall"]:
                    if value is not None:
                        self.config["swall"][option.dest] = value
                elif value is not None and value != self.config["swall"][option.dest]:
                    self.config["swall"][option.dest] = value

    def parse_args(self, args=None, values=None):
        options, args = super(ConfParser, self).parse_args(args, values)
        self.process_config_dir()
        return options, args

    def process_config_dir(self):
        self.options.config_dir = os.path.abspath(self.options.config_dir)
        if hasattr(self, 'setup_config'):
            self.config = self.setup_config()
            self.__merge_config_with_cli()

    def get_config_file_path(self, configfile):
        return os.path.join(self.options.config_dir, configfile)


class ConfMin(object):
    def _mixin_setup(self):
        group = optparse.OptionGroup(
            self, "Options for conf_dir"
        )
        self.add_option_group(group)
        group.add_option(
            '-c', '--config_dir', dest='config_dir',
            default='/data/swall/conf',
            help='Pass in an alternative configuration dir. Default: %default'
        )


class DaemonMin(object):
    def _mixin_setup(self):
        group = optparse.OptionGroup(
            self, "Options for swalld daemon"
        )
        self.add_option_group(group)
        group.add_option(
            '-D', dest='daemon',
            default=True,
            action='store_false',
            help='Run the {0} as a non daemon'.format(self.get_prog_name())
        )
        group.add_option(
            '-C', '--cache_dir', dest='cache',
            help='Specify the cache dir'
        )
        group.add_option(
            '-B', '--backup_dir', dest='backup',
            help='Specify the backup dir'
        )
        group.add_option(
            '-p', '--pid_file', dest='pidfile',
            help='Specify the location of the pidfile. Default: %default'
        )

    def daemonize_if_required(self):
        if self.options.daemon:
            daemonize()

    def set_pidfile(self):
        set_pidfile(self.config["swall"]['pidfile'])


class CtlMin(object):
    def _mixin_setup(self):
        group = optparse.OptionGroup(
            self, "Options for swall ctl"
        )
        self.add_option_group(group)
        group.add_option('-e', '--exclude',
                         default='',
                         dest='exclude',
                         help='Specify the exclude hosts by regix'
        )
        group.add_option('-t', '--timeout',
                         default=30,
                         dest='timeout',
                         help='Specify the timeout,the unit is second'
        )
        group.add_option('-r', '--is_raw',
                         action="store_true",
                         default=False,
                         dest='is_raw',
                         help='Specify the raw output'
        )
        group.add_option('-n', '--nthread',
                         default=-1,
                         dest='nthread',
                         help='Specify running nthread'
        )
        group.add_option('-F', '--no_format',
                         action="store_true",
                         default=False,
                         dest='no_format',
                         help='Do not format the output'
        )


class MainParser(object):
    def __init__(self, *args, **kwargs):
        self.usage = "Usage: %s [OPTIONS] COMMAND [arg...]" % sys.argv[0]
        self.description = """
A approach to infrastructure management.

  Commands:
    server     manage a agent server:start,stop,restart
    ctl        Send functions to swall server
    init       init zookeeper db for swall server

"""

    def print_help(self, file=None):
        """
        overwrite the print_help
        """
        if file is None:
            file = sys.stdout
        result = []
        result.append(self.usage)
        result.append(self.description)
        file.write("%s\n" % "".join(result))


class InitParser(ConfParser, ConfMin):
    __metaclass__ = OptionParserMeta

    def __init__(self, *args, **kwargs):
        super(InitParser, self).__init__(*args, **kwargs)
        self.usage = '%prog init [OPTIONS]'
        self.description = """
Init zookeeper db for swall at first.

"""

    def _mixin_setup(self):
        group = optparse.OptionGroup(
            self, "Options for init zookeeper"
        )
        self.add_option_group(group)
        group.add_option(
            '-f', "--force", dest='force',
            default=False,
            action='store_true',
            help='Force init zookeeper db'
        )


class ServerParser(ConfParser, DaemonMin, ConfMin):
    __metaclass__ = OptionParserMeta

    def __init__(self, *args, **kwargs):
        super(ServerParser, self).__init__(*args, **kwargs)
        self.usage = '%prog server [OPTIONS] COMMAND'
        self.description = """
Run swall server.

  Commands:
    start       start swall server
    stop        stop swall server
    restart     restart swall server
    status      show the status of the swall server

"""


class CtlParser(ConfParser, CtlMin, ConfMin):
    __metaclass__ = OptionParserMeta

    def __init__(self, *args, **kwargs):
        super(CtlParser, self).__init__(*args, **kwargs)
        self.usage = '%prog ctl  <role> [target] <module.function> [arguments]'
        self.description = """
Send command to swall server.

"""


class Ctl(CtlParser):
    """
    发送命令
    """

    def main(self):
        self.parse_args()
        job = Job(self.config, env="aes")
        args = self.args[1:]

        if len(args) < 2:
            self.print_help()
            sys.exit(1)
            #解析参数，获取位置参数和关键字参数
        args, kwargs = parse_args_and_kwargs(args)
        rets = job.submit_job(
            cmd=args[2],
            roles=args[0],
            nregex=args[1],
            nexclude=self.options.exclude,
            args=args[3:],
            kwargs=kwargs,
            wait_timeout=self.options.timeout,
            nthread=int(self.options.nthread)
        )
        if rets.get("extra_data"):
            rets = sort_ret(rets.get("extra_data"))
        else:
            print c('#' * 50, 'y')
            print color(rets.get("msg"), 'r')
            print c('#' * 50, 'y')
            sys.exit(1)
        if not self.options.is_raw:
            format_ret = enumerate(
                [u"%s %s : %s" % (u"[%s]" % c(ret[0], 'y'), c(ret[1], 'g'), color(ret[2])) for ret in rets])
        else:
            format_ret = enumerate(
                [u"%s %s : %s" % (u"[%s]" % ret[0], ret[1], ret[2]) for ret in rets])
        print c('#' * 50, 'y')

        for index, item in format_ret:
            print item.encode("utf-8")

        print c('#' * 50, 'y')

        if locals().get('index') >= 0:
            index += 1
        else:
            index = 0
        print "一共执行了[%s]个" % color(index)


class SwallAgent(ServerParser):
    """
    swall进程管理
    """

    def main(self):
        self.parse_args()
        if self.args[1:]:
            action = self.args[1]
        else:
            self.print_help()
            sys.exit(1)
        cmds = {
            "start": self.start,
            "stop": self.stop,
            "restart": self.restart,
            "status": self.status
        }
        func = cmds.get(action)
        if func:
            func()
        else:
            self.print_help()
            sys.exit(1)

    def status(self):
        """
        show status
        """
        try:
            pid = open(self.config["swall"]["pidfile"], 'r').read()
            message = c("swall is running[%s]...\n" % pid, 'g')
        except IOError:
            message = c("swall is not running!\n", 'r')
        sys.stdout.write(message)
        sys.stdout.flush()

    def stop(self):
        """
        stop server
        """
        kill_daemon(self.config["swall"]["pidfile"])

    def start(self):
        """
        restart server
        """
        self.daemonize_if_required()
        logger.setup_file_logger(self.config["swall"]["log_file"], self.config["swall"]["log_level"])
        try:
            sagent = Agent(self.config)
            self.set_pidfile()
            sagent.loop()
        except KeyboardInterrupt:
            print "Stopping the Swall Agent"
            self.stop()
            logging.getLogger().warn()

    def restart(self):
        self.stop()
        self.start()


class ZKInit(InitParser, ConfMin):
    __metaclass__ = OptionParserMeta

    def main(self):
        """
        init zookeeper
        """
        self.parse_args()
        keeper = Keeper(self.config)
        if keeper.init_db(self.options.force):
            sys.stdout.write(c("init zookeeper db ok\n", 'g'))
        else:
            sys.stdout.write(c("init zookeeper db fail\n", 'r'))
        sys.stdout.flush()


class Swall(MainParser):
    def main(self):
        """
        get args for commands
        """
        if not sys.argv[1:]:
            self.print_help()
            sys.exit(1)
        cmd = sys.argv[1]
        self._sub_commands(cmd)

    def _sub_commands(self, cmd):
        if cmd == "server":
            agent = SwallAgent()
            agent.main()
        elif cmd == "init":
            init = ZKInit()
            init.main()
        elif cmd == "ctl":
            ctl = Ctl()
            ctl.main()
        else:
            self.print_help()

