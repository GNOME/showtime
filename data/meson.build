desktop_file = i18n.merge_file(
  input: configure_file(
    input: 'org.gnome.Showtime.desktop.in',
    output: app_id + '.desktop.in',
    configuration: conf,
  ),
  output: app_id + '.desktop',
  type: 'desktop',
  po_dir: '../po',
  install: true,
  install_dir: get_option('datadir') / 'applications',
)

desktop_utils = find_program('desktop-file-validate', required: false)
if desktop_utils.found()
  test('Validate desktop file', desktop_utils, args: [desktop_file])
endif

appstream_file = i18n.merge_file(
  input: configure_file(
    input: 'org.gnome.Showtime.metainfo.xml.in',
    output: app_id + '.metainfo.xml.in',
    configuration: conf,
  ),
  output: app_id + '.metainfo.xml',
  po_dir: '../po',
  install: true,
  install_dir: get_option('datadir') / 'metainfo',
)

appstreamcli = find_program('appstreamcli', required: false, disabler: true)
test(
  'Validate appstream file',
  appstreamcli,
  args: ['validate', '--no-net', '--explain', appstream_file],
)

schema_file = configure_file(
  input: 'org.gnome.Showtime.gschema.xml.in',
  output: app_id + '.gschema.xml',
  configuration: conf,
  install_dir: get_option('datadir') / 'glib-2.0' / 'schemas',
)

compile_schemas = find_program('glib-compile-schemas')
# gnome.compile_schemas only looks at the source tree
custom_target(
  bin_name + '-schemas',
  input: schema_file,
  output: 'gschemas.compiled',
  command: [compile_schemas, meson.current_build_dir()],
  build_by_default: true,
)
meson.add_devenv({'GSETTINGS_SCHEMA_DIR': meson.current_build_dir()})

configure_file(
  input: 'org.gnome.Showtime.service.in',
  output: app_id + '.service',
  configuration: conf,
  install_dir: get_option('datadir') / 'dbus-1' / 'services'
)

subdir('icons')
