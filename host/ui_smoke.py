"""Run real Tk widgets without hardware; all output belongs to a fresh profile.

This is a source UI contract probe, not screenshot or real-board acceptance.
The explicit-exit probe uses a command spy and a temporary enabled flag; no
board packets, song results, waveforms or worker replies are synthesized.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import time
import traceback


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-root', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    profile = args.data_root.resolve()
    if profile.exists() and any(profile.iterdir()):
        parser.error('data-root must be a fresh/empty isolated directory')
    profile.mkdir(parents=True, exist_ok=True)
    os.environ['NEXYS_PORTABLE_RUNTIME'] = '1'
    os.environ['NEXYS_MONITOR_DATA'] = str(profile)
    from monitor_gui import Dashboard
    import psutil
    import tkinter as tk
    report = {'hardware_used': False, 'network_used': False, 'data_root': str(profile),
              'checks': {}, 'layout': [], 'callback_errors': []}
    app = None
    try:
        app = Dashboard(auto_connect=False)
        def callback_error(kind, value, tb):
            report['callback_errors'].append(''.join(traceback.format_exception(kind, value, tb)))
        app.root.report_callback_exception = callback_error
        def pump(milliseconds=120):
            deadline = time.monotonic() + milliseconds / 1000
            while time.monotonic() < deadline:
                app.root.update()
                time.sleep(.005)
        def layout_observations(page):
            flow_clipping, labels = [], []
            def walk(widget):
                if not widget.winfo_ismapped():
                    return
                if widget in app.pages.values() and widget is not app.pages[page]:
                    return
                if widget.__class__.__name__ in ('FlowBar', '_WrapRow'):
                    for child in widget.winfo_children():
                        if not child.winfo_ismapped():
                            continue
                        x, y, width, height = child.winfo_x(), child.winfo_y(), child.winfo_width(), child.winfo_height()
                        if x < -1 or y < -1 or x + width > widget.winfo_width() + 1 or y + height > widget.winfo_height() + 1:
                            flow_clipping.append({'widget': str(child), 'bounds': [x, y, width, height],
                                                  'parent_size': [widget.winfo_width(), widget.winfo_height()]})
                if widget.winfo_class() in ('TLabel', 'Label') and widget.winfo_reqwidth() > widget.winfo_width() + 2:
                    try:
                        wraps = float(widget.cget('wraplength') or 0) > 0
                    except (tk.TclError, ValueError):
                        wraps = False
                    if not wraps:
                        labels.append({'widget': str(widget), 'requested_width': widget.winfo_reqwidth(),
                                       'actual_width': widget.winfo_width()})
                for child in widget.winfo_children():
                    walk(child)
            walk(app.root)
            return {'flow_control_clipping': flow_clipping, 'potential_label_clipping': labels}
        def minimum_monitor_scroll():
            viewport = app.monitor_scroll
            pump(200)
            region = tuple(float(value) for value in str(viewport.cget('scrollregion')).split())
            span = region[3] - region[1]
            details = {'viewport_size': [viewport.winfo_width(), viewport.winfo_height()],
                       'scrollregion': list(region), 'items': {}}
            def bounds(widget):
                x = widget.winfo_rootx() - viewport.winfo_rootx()
                y = widget.winfo_rooty() - viewport.winfo_rooty()
                return [x, y, widget.winfo_width(), widget.winfo_height()]
            def inside(box):
                x, y, width, height = box
                return x >= -1 and y >= -1 and x + width <= viewport.winfo_width() + 1 and y + height <= viewport.winfo_height() + 1
            widgets = {**app.plots, 'io': app.io_canvas.master}
            for name, widget in widgets.items():
                for attempt in range(3):
                    # Responsive reflow can update the document extent while
                    # scrolling. Resolve coordinates from the current layout.
                    current_region = tuple(float(value) for value in str(viewport.cget('scrollregion')).split())
                    current_span = current_region[3] - current_region[1]
                    document_y = widget.winfo_rooty() - viewport.winfo_rooty() + viewport.canvasy(0)
                    viewport.yview_moveto(max(0, (document_y - 8 - current_region[1]) / current_span))
                    pump(120)
                    box = bounds(widget)
                    if inside(box):
                        break
                details['items'][name] = {'bounds': box, 'mapped': bool(widget.winfo_ismapped()),
                                          'fully_visible_when_scrolled': inside(box), 'layout_attempts': attempt + 1}
            viewport.yview_moveto(1.0)
            pump(80)
            details['bottom'] = {'io_bounds': bounds(app.io_canvas.master),
                                 'io_fully_visible': inside(bounds(app.io_canvas.master)),
                                 'yview': list(viewport.yview())}
            details['final_scrollregion'] = [float(value) for value in str(viewport.cget('scrollregion')).split()]
            details['passed'] = viewport.winfo_height() >= 150 and span > viewport.winfo_height() and all(
                item['mapped'] and item['fully_visible_when_scrolled'] for item in details['items'].values()) and details['bottom']['io_fully_visible']
            viewport.yview_moveto(0)
            pump(80)
            return details
        pump(400)
        report['checks']['no_serial_worker'] = app.worker is None
        report['checks']['no_fabricated_live_data'] = app.last_row is None and not app.audio and not app.xyz
        app.open_music()
        pump(300)
        panel = app.music_panel
        engine = panel.engine
        worker_pid = engine.process.pid
        commands = []
        original_action = app.action
        app.action = lambda name, **values: commands.append((name, values))
        panel.enabled = True  # Callback contract only; never sent to a device.
        for page in ['monitor', 'events', 'audio']:
            app.nav_buttons[page].invoke()
            pump(50)
        report['checks']['navigation_keeps_background_controller'] = app.music_panel is panel and panel.engine is engine and not commands
        panel.hide()
        report['checks']['explicit_exit_retains_disable'] = commands == [('music_disable', {})] and app.active_page == 'monitor'
        panel.enabled = False
        app.action = original_action
        # Populate no business data. Verify layout against real widget geometry.
        for width, height in [(960, 600), (1280, 800), (1460, 960)]:
            app.root.state('normal')
            app.root.geometry(f'{width}x{height}')
            for theme in ['浅色', '深色']:
                app.theme_choice.set(theme)
                app.theme_manager.set(theme)
                for page in ['monitor', 'events', 'audio']:
                    app.nav_buttons[page].invoke()
                    pump()
                    if width == 960 and page == 'monitor':
                        report.setdefault('minimum_monitor_scroll', []).append({'theme': theme, **minimum_monitor_scroll()})
                    report['layout'].append({'requested_size': [width, height], 'theme': theme, 'page': page,
                                             'actual_size': [app.root.winfo_width(), app.root.winfo_height()],
                                             'page_size': [app.pages[page].winfo_width(), app.pages[page].winfo_height()],
                                             **layout_observations(page)})
        pump()
        before = psutil.Process().memory_info().rss
        timers_before = len(app.root.tk.call('after', 'info'))
        stress_samples = []
        for index in range(20):
            app.theme_manager.set('浅色' if index % 2 else '深色')
            app.nav_buttons[['monitor', 'events', 'audio'][index % 3]].invoke()
            pump(50)
            stress_samples.append({'switch': index + 1, 'rss_bytes': psutil.Process().memory_info().rss,
                                   'timer_count': len(app.root.tk.call('after', 'info'))})
        pump(200)
        report['stress'] = {'switches': 20, 'rss_before': before,
                            'rss_after': psutil.Process().memory_info().rss,
                            'timers_before': timers_before,
                            'timers_after': len(app.root.tk.call('after', 'info')),
                            'samples': stress_samples}
        report['checks']['same_audio_controller_after_stress'] = app.music_panel is panel and panel.engine is engine
        report['checks']['same_idle_worker_after_stress'] = engine.process.pid == worker_pid and engine.process.poll() is None
        report['checks']['no_timer_accumulation'] = report['stress']['timers_after'] <= timers_before + 4
        report['checks']['no_callback_errors'] = not report['callback_errors']
        report['checks']['usable_page_geometry'] = all(item['page_size'][0] >= 500 and item['page_size'][1] >= 150 for item in report['layout'])
        report['checks']['no_flow_control_clipping'] = not any(item['flow_control_clipping'] for item in report['layout'])
        report['checks']['minimum_monitor_scroll_accessible'] = len(report.get('minimum_monitor_scroll', [])) == 2 and all(
            item['passed'] for item in report['minimum_monitor_scroll'])
        # Freeze only the actual empty chart grids/text; no board data is added.
        app.show_page('monitor')
        app.theme_manager.set('浅色')
        pump()
        app.pause()
        def canvas_items(canvas):
            return {item: {'coords': canvas.coords(item), 'fill': canvas.itemcget(item, 'fill')}
                    for item in canvas.find_all()}
        before_items = {key: canvas_items(plot.canvas) for key, plot in app.plots.items()}
        app.theme_manager.set('深色')
        pump()
        after_items = {key: canvas_items(plot.canvas) for key, plot in app.plots.items()}
        report['paused_canvas'] = {
            'item_counts': {key: len(items) for key, items in before_items.items()},
            'changed_fills': sum(before_items[key][item]['fill'] != after_items[key][item]['fill']
                                 for key in before_items for item in before_items[key]
                                 if item in after_items[key]),
        }
        report['checks']['paused_theme_preserves_canvas_coordinates'] = all(
            before_items[key].keys() == after_items[key].keys()
            and all(before_items[key][item]['coords'] == after_items[key][item]['coords'] for item in before_items[key])
            for key in before_items)
        report['checks']['paused_theme_changes_existing_fills'] = report['paused_canvas']['changed_fills'] > 0
        app.pause()
        # Construct the real wizard in a fresh profile, without pressing Next.
        wizard_commands = []
        app.action = lambda name, **values: wizard_commands.append((name, values))
        panel.open_acceptance()
        wizard = panel.wizard
        pump()
        title = next(widget for widget in wizard.win.winfo_children()
                     if 'textvariable' in widget.keys() and str(widget.cget('textvariable')) == str(wizard.title))
        title_colors = {}
        for choice in ['浅色', '深色']:
            app.theme_manager.set(choice)
            pump()
            title_colors[choice] = str(title.cget('foreground')).lower()
            report['checks']['wizard_title_ink_' + choice] = title_colors[choice] == app.theme_manager.palette['ink']
        report['wizard'] = {'title_colors': title_colors, 'mode': wizard.mode,
                            'active': wizard.active, 'result_count': len(wizard.results)}
        report['checks']['wizard_started_no_recording'] = wizard.mode == 'ready' and wizard.active is None and not wizard.results and not wizard_commands
        app.action = original_action
        # Cancel only this Toplevel's owned after callback before destroying it.
        owned_commands = set(wizard.win._tclCommands or [])
        for identifier in wizard.win.tk.call('after', 'info'):
            script = str(wizard.win.tk.call('after', 'info', identifier)[0])
            if any(command in script for command in owned_commands):
                wizard.win.after_cancel(identifier)
        wizard.win.destroy()
        del panel.wizard
        pump()
        report['checks']['no_callback_errors'] = not report['callback_errors']
    except Exception:
        report['exception'] = traceback.format_exc()
    finally:
        if app:
            try:
                app.close()
            except Exception:
                report['close_exception'] = traceback.format_exc()
        report['passed'] = bool(report['checks']) and all(report['checks'].values()) and not report.get('exception') and not report.get('close_exception')
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
