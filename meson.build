project(
  'showtime',
  version: '49.beta',
  meson_version: '>= 0.62.0',
  default_options: [
    'warning_level=2',
    'werror=false',
  ],
)

dependency('gtk4', version: '>= 4.18.0')
dependency('libadwaita-1', version: '>= 1.8.alpha')
dependency('blueprint-compiler', version: '>= 0.17')

i18n = import('i18n')
gnome = import('gnome')
python = import('python')

py_installation = python.find_installation('python3')

python_dir = join_paths(get_option('prefix'), py_installation.get_install_dir())
pkgdatadir = get_option('prefix') / get_option('datadir') / meson.project_name()

profile = get_option('profile')
if profile == 'development'
  app_id = 'org.gnome.Showtime.Devel'
  prefix = '/org/gnome/Showtime/Devel'
elif profile == 'release'
  app_id = 'org.gnome.Showtime'
  prefix = '/org/gnome/Showtime'
endif

conf = configuration_data()
conf.set('PYTHON', python.find_installation('python3').full_path())
conf.set('VERSION', meson.project_version())
conf.set('APP_ID', app_id)
conf.set('PREFIX', prefix)
conf.set('PROFILE', profile)
conf.set('localedir', get_option('prefix') / get_option('localedir'))
conf.set('pkgdatadir', pkgdatadir)
conf.set('bindir', get_option('bindir'))
conf.set('prefix', get_option('prefix'))

subdir('data')
subdir('showtime')
subdir('po')

gnome.post_install(
  glib_compile_schemas: true,
  gtk_update_icon_cache: true,
  update_desktop_database: true,
)
