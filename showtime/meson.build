moduledir = python_dir / 'showtime'

blueprints = custom_target(
  'blueprints',
  input: files(
    'gtk/help-overlay.blp',
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
  output: 'showtime',
  configuration: conf,
  install: true,
  install_dir: get_option('bindir'),
  install_mode: 'r-xr-xr-x',
)

showtime_sources = [
  '__init__.py',
  'application_delegate.py',
  'drag_overlay.py',
  'main.py',
  'messenger.py',
  'mpris.py',
  'play.py',
  'utils.py',
  'window.py',
  configure_file(input: 'shared.py.in', output: 'shared.py', configuration: conf),
]

install_data(showtime_sources, install_dir: moduledir)
install_subdir('logging', install_dir: moduledir)
