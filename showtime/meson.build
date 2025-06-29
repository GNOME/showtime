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
  output: 'showtime',
  configuration: conf,
  install: true,
  install_dir: get_option('bindir'),
  install_mode: 'rwxr-xr-x',
)

showtime_sources = [
  configure_file(input: '__init__.py.in', output: '__init__.py', configuration: conf),
  'application_delegate.py',
  'main.py',
  'mpris.py',
  'play.py',
  'utils.py',
]

install_subdir('widgets', install_dir: moduledir)
install_data(showtime_sources, install_dir: moduledir)
