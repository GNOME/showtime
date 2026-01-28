moduledir = python_dir / 'showtime'

blueprints = custom_target(
  'blueprints',
  input: files(
    'gtk/options.blp',
    'gtk/shortcuts-dialog.blp',
    'gtk/sound-options.blp',
    'gtk/window.blp',
  ),
  output: '.',
  command: [
    find_program('blueprint-compiler'),
    'batch-compile',
    '@OUTPUT@',
    '@CURRENT_SOURCE_DIR@',
    '@INPUT@',
  ],
)

gnome.compile_resources(
  'showtime',
  configure_file(
    input: 'showtime.gresource.xml.in',
    output: 'showtime.gresource.xml',
    configuration: conf,
  ),
  gresource_bundle: true,
  install: true,
  install_dir: pkgdatadir,
  dependencies: blueprints,
)

configure_file(
  input: 'showtime.in',
  output: bin_name,
  configuration: conf,
  install: true,
  install_dir: get_option('bindir'),
  install_mode: 'rwxr-xr-x',
)

showtime_widgets_sources = [
  'widgets/__init__.py',
  'widgets/drag_overlay.py',
  'widgets/options.py',
  'widgets/sound_options.py',
  'widgets/window.py',
]

showtime_sources = [
  configure_file(input: '__init__.py.in', output: '__init__.py', configuration: conf),
  'main.py',
  'mpris.py',
  'play.py',
  'utils.py',
]

py_installation.install_sources(showtime_widgets_sources, subdir: 'showtime/widgets')
py_installation.install_sources(showtime_sources, subdir: 'showtime')
