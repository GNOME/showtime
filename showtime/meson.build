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
    find_program('blueprint-compiler', version: '>= 0.17'),
    'batch-compile',
    '@OUTPUT@',
    '@CURRENT_SOURCE_DIR@',
    '@INPUT@',
  ],
)

resources = gnome.compile_resources(
  'showtime',
  configure_file(
    input: 'showtime.gresource.xml.in',
    output: 'showtime.gresource.xml',
    configuration: conf,
  ),
  dependencies: blueprints,
)

showtime_sources = [
  '__init__.py',
  'application_delegate.py',
  'application.py',
  'mpris.py',
  'play.py',
  'utils.py',
]

install_subdir('widgets', install_dir: moduledir)
install_data(showtime_sources, install_dir: moduledir)

launcher_sources = [
  'showtime.c',
  configure_file(output: 'config.h', configuration: conf),
]

executable(
  bin_name,
  launcher_sources + resources,
  dependencies: [py3_dep, adw_dep, gtk_dep],
  install: true,
  c_args: ['-DG_LOG_DOMAIN="@0@"'.format(app_id), '-DG_LOG_USE_STRUCTURED'],
)
