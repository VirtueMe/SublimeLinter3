#
# commands.py
# Part of SublimeLinter3, a code checking framework for Sublime Text 3
#
# Written by Ryan Hileman and Aparajita Fishman
#
# Project: https://github.com/SublimeLinter/SublimeLinter3
# License: MIT
#

import sublime
import sublime_plugin

import os
from threading import Thread

from . import sublimelinter
from .lint import persist
from .lint.highlight import Highlight


def error_command(f):
    '''A decorator that only executes f if the current view has errors.'''
    def run(self, edit, **kwargs):
        vid = self.view.id()

        if vid in persist.errors and persist.errors[vid]:
            f(self, self.view, persist.errors[vid], **kwargs)
        else:
            sublime.error_message('No lint errors.')

    return run


def select_line(view, line):
    sel = view.sel()
    point = view.text_point(line, 0)
    sel.clear()
    sel.add(view.line(point))


class sublimelinter_find_error(sublime_plugin.TextCommand):
    '''This command is just a superclass for other commands, it is never enabled.'''
    def is_enabled(self):
        vid = self.view.id()
        return vid in persist.linters

    def find_error(self, view, errors, forward=True):
        sel = view.sel()
        saved_sel = tuple(sel)

        if len(sel) == 0:
            sel.add((0, 0))

        point = sel[0].begin() if forward else sel[-1].end()
        regions = sublime.Selection(view.id())
        regions.clear()
        regions.add_all(view.get_regions(Highlight.MARK_KEY_FORMAT.format(Highlight.WARNING)))
        regions.add_all(view.get_regions(Highlight.MARK_KEY_FORMAT.format(Highlight.ERROR)))
        region_to_select = None

        # If going forward, find the first region beginning after the point.
        # If going backward, find the first region ending before the point.
        # If nothing is found in the given direction, wrap to the first/last region.
        if forward:
            for region in regions:
                if point < region.begin():
                    region_to_select = region
                    break
        else:
            for region in reversed(regions):
                if point > region.end():
                    region_to_select = region
                    break

        # If there is only one error line and the cursor is in that line, we cannot move.
        # Otherwise wrap to the first/last error line unless settings disallow that.
        if region_to_select is None and ((len(regions) > 1 or not regions[0].contains(point))):
            if persist.settings.get('wrap_find', True):
                region_to_select = regions[0] if forward else regions[-1]

        if region_to_select is not None:
            self.select_lint_region(self.view, region_to_select)
        else:
            sel.clear()
            sel.add_all(saved_sel)
            sublime.error_message('No {0} lint errors.'.format('next' if forward else 'previous'))

        return region_to_select

    def select_lint_region(self, view, region):
        sel = view.sel()
        sel.clear()

        # Find the first marked region within the region to select.
        # If there are none, put the cursor at the beginning of the line.
        marked_region = self.find_mark_within(view, region)

        if marked_region is None:
            marked_region = sublime.Region(region.begin(), region.begin())

        sel.add(marked_region)
        view.show(marked_region, show_surrounds=True)

    def find_mark_within(self, view, region):
        marks = view.get_regions(Highlight.MARK_KEY_FORMAT.format(Highlight.WARNING))
        marks.extend(view.get_regions(Highlight.MARK_KEY_FORMAT.format(Highlight.ERROR)))
        marks.sort(key=lambda x: x.begin())

        for mark in marks:
            if region.contains(mark):
                return mark

        return None


class sublimelinter_next_error(sublimelinter_find_error):
    '''Place the caret at the next error.'''
    @error_command
    def run(self, view, errors):
        self.find_error(view, errors, forward=True)


class sublimelinter_previous_error(sublimelinter_find_error):
    '''Place the caret at the previous error.'''
    @error_command
    def run(self, view, errors):
        self.find_error(view, errors, forward=False)


class sublimelinter_all_errors(sublime_plugin.TextCommand):
    '''Show a quick panel with all of the errors in the current view.'''
    @error_command
    def run(self, view, errors):
        options = []
        option_to_line = []

        for lineno, messages in sorted(errors.items()):
            line = view.substr(
                view.full_line(view.text_point(lineno, 0))
            )

            while messages:
                option_to_line.append(lineno)
                options.append(
                    [("%i| %s" % (lineno + 1, line.strip()))] +
                    [m for m in messages[:2]]
                )

                messages = messages[2:]

        def center_line(i):
            if i != -1:
                select_line(view, option_to_line[i])
                view.show_at_center(view.sel()[0])

        view.window().show_quick_panel(options, center_line, sublime.MONOSPACE_FONT)


class sublimelinter_report(sublime_plugin.WindowCommand):
    '''
    Display a report of all errors in all open files in the current window,
    in all files in all folders in the current window, or both.
    '''
    def run(self, on='files'):
        output = self.window.new_file()
        output.set_name(persist.plugin_name)
        output.set_scratch(True)

        if on == 'files' or on == 'both':
            for view in self.window.views():
                self.report(output, view)

        if on == 'folders' or on == 'both':
            for folder in self.window.folders():
                self.folder(output, folder)

    def folder(self, output, folder):
        for root, dirs, files in os.walk(folder):
            for name in files:
                path = os.path.join(root, name)

                # Ignore files over 256K to speed things up a bit
                if os.stat(path).st_size < 256 * 1024:
                    # TODO: not implemented
                    pass

    def report(self, output, view):
        def finish_lint(view, linters):
            if not linters:
                return

            def insert(edit):
                if not any(l.errors for l in linters):
                    return

                filename = os.path.basename(linters[0].filename or 'untitled')
                out = '\n{}:\n'.format(filename)

                for linter in linters:
                    if linter.errors:
                        for line, errors in sorted(linter.errors.items()):
                            for col, error in errors:
                                out += '  {}: {}\n'.format(line, error)

                output.insert(edit, output.size(), out)

            persist.edits[output.id()].append(insert)
            output.run_command('sublimelinter_edit')

        args = (view.id(), finish_lint)
        Thread(target=sublimelinter.SublimeLinter.lint, args=args).start()
