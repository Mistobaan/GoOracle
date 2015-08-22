# Copyright (c) 2014 Jesse Meek <https://github.com/waigani>
# This program is Free Software see LICENSE file for details.

# API reference: https://www.sublimetext.com/docs/3/api_reference.html

"""
GoOracle is a Go oracle plugin for Sublime Text 3.
It depends GoSublime and the oracle tool being installed:
go get -u golang.org/x/tools/cmd/oracle
"""

oracle_commands = """
callees     show possible targets of selected function call
callers     show possible callers of selected function
callstack   show path from callgraph root to selected function
definition  show declaration of selected identifier
describe    describe selected syntax: definition, methods, etc
freevars    show free variables of selection
implements  show 'implements' relation for selected type or method
peers       show send/receive corresponding to selected channel op
referrers   show all refs to entity denoted by selected identifier
what        show basic information about the selected syntax node
"""

descriptions = [ desc.strip() for desc in oracle_commands.split("\n") if desc.strip() ]
commands = [ desc.split()[0].strip() for desc in descriptions ]

import sublime, sublime_plugin, subprocess, time

from gosubl import sh, gs
import os

def return_package_if_inside_gopath(filename):
    env = sh.env()
    gopaths = env["GOPATH"].split(":")
    new_lines = []
    for path in gopaths:
        print("GOPATH", path)
        print("FILENA", filename)
        path = os.path.join(path,"src")
        if filename.startswith(path):
            dirname=os.path.dirname(filename.replace(path,""))
            print(dirname)
            return dirname
    return ""

class GoOracleCommand(sublime_plugin.TextCommand):

    def run(self, edit, command=None):
        if command:
            self.run_oracle(command)
            return

        # Call oracle cmd with the given mode.
        def on_done(i):
            if i < 0:
                return
            self.run_oracle(command[i])
        self.view.window().show_quick_panel(descriptions, on_done)

    def run_oracle(self, command, scope=""):
        if scope == "" and (command in ["callees", "callers", "callstack", "peers", "pointsto"]):
            self.choose_scope(command)
            return

        byte_begin, byte_end = self.extract_current_selection(self.view)
        out, err = self.oracle(byte_end, begin_offset=byte_begin, mode=command, scope=scope)
        self.write_out(out, err, command)

    def extract_current_selection(self, view):
        region = view.sel()[0]
        return region.a, region.b

        text = view.substr(sublime.Region(region.a, region.b))
        print("text selected:", text)

        cb_map = self.get_map(text)
        byte_end = cb_map[sorted(cb_map.keys())[-1]]
        byte_begin = None
        if not region.empty():
            byte_begin = cb_map[region.begin()-1]

        return byte_begin, byte_end

    def choose_scope(self, command):
        #return_package_if_inside_gopath(self.view.file_name())
        sublime.status_message("loading packages in current go path ...")
        cr = sh.go_cmd(["list", "..."]).run()
        if cr.exc:
            _print('error running go list ./...')
        print("error:", cr.err)
        print("output:", cr.out)
        options = cr.out.split("\n")

        def on_done(idx):
            if idx < 0:
                return
            self.run_oracle(command, scope=options[idx])

        self.view.window().show_quick_panel(options, on_done)

    def write_out(self, result, err, mode):
        """ Write the oracle output to a new file.
        """
        if err.strip() != '':
            print(err)
            sublime.error_message(err)
            return

        options = [ line.strip() for line in result.split("\n") if line.strip() ]
        def choose_selection(i):
            if i < 0:
                return
            print("selected:", options[i])
            filename, row, col = options[i].split()[0].split(":")[:3]
            if "." in row:
                row, col = row.split(".")[:2]
                if "-" in col:
                    col = col.split("-")[0]
            print("open file", filename, int(row), int(col))
            self.view.window().open_file(filename+":"+row+":"+col, sublime.ENCODED_POSITION|sublime.TRANSIENT)
            #window.focus_view(view)
        if not options:
            def nothing(i):
                pass
            self.view.window().show_quick_panel(["no results"], nothing)
            return
        sublime.status_message(options[0])
        options = options[1:]

        self.view.window().show_quick_panel(options, choose_selection, 0,0, choose_selection)
        return
        window = self.view.window()
        view = None
        buff_name = 'Oracle Output'

        # If the output file is already open, use that.
        for v in window.views():
            if v.name() == buff_name:
                view = v
                break
        # Otherwise, create a new one.
        if view is None:
            view = window.new_file()
            view.set_name(buff_name)

        # Run a new command to use the edit object for this view.
        view.run_command('go_oracle_write_to_file', {
            'result': result,
            'err': err,
            'mode': mode})
        window.focus_view(view)

    def get_map(self, chars):
        """ Generate a map of character offset to byte offset for the given string 'chars'.
        """

        byte_offset = 0
        cb_map = {}

        for char_offset, char in enumerate(chars):
            cb_map[char_offset] = byte_offset
            byte_offset += len(char.encode('utf-8'))
        return cb_map

    def oracle(self, end_offset, begin_offset=None, mode="plain", scope=""):
        """ Builds the oracle shell command and calls it, returning it's output as a string.
        """
        file_path = self.view.file_name()
        output_format = "plain"
        pos = "#" + str(end_offset)
        if begin_offset is not None:
            pos = "#%i,#%i" %(begin_offset, end_offset)

        oracle = sh.which("oracle")
        if oracle:
            args = ["-pos="+file_path+":"+pos, "-format="+output_format, mode]
            if scope:
                args.append(scope)
            shcmd = gs.lst(oracle, args)
            print(" ".join(shcmd))
            cmd = sh.Command(shcmd)
            cr = cmd.run()
            if cr.exc:
                _print('error loading env vars: %s' % cr.exc)
            return cr.out, cr.err
        return

class GoOracleWriteToFileCommand(sublime_plugin.TextCommand):
    """ Writes the oracle output to the current view.
    """

    def run(self, edit, result, err, mode):
        view = self.view

        content = mode
        if result:
            content += "\n\n" + result
        if err:
            content += "\nErrors Found:\n\n"+ err

        view.replace(edit, sublime.Region(0, view.size()), content)
        view.sel().clear()


def get_setting(key, default=None):
    """ Returns the user setting if found, otherwise it returns the
    default setting. If neither are set the 'default' value passed in is returned.
    """

    val = sublime.load_settings("User.sublime-settings").get(key)
    if not val:
        val = sublime.load_settings("Default.sublime-settings").get(key)
    if not val:
        val = default
    return val
