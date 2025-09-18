project(
  'showtime', 'c',
  version: '49.0',
  meson_version: '>= 0.62.0',
  default_options: [
    'warning_level=2',
    'werror=false',
  ],
)

adw_dep = dependency('libadwaita-1', version: '>= 1.8.alpha')
gtk_dep = dependency('gtk4', version: '>= 4.18.0')
py3_dep = dependency('python3-embed', version: '>= 3.8')

i18n = import('i18n')
gnome = import('gnome')
python = import('python')

py_installation = python.find_installation('python3')

python_dir = join_paths(get_option('prefix'), py_installation.get_install_dir())

profile = get_option('profile')
if profile == 'development'
  app_id = 'org.gnome.Showtime.Devel'
  prefix = '/org/gnome/Showtime/Devel'
elif profile == 'release'
  app_id = 'org.gnome.Showtime'
  prefix = '/org/gnome/Showtime'
endif

bin_name = 'showtime'

conf = configuration_data()
conf.set('PYTHON', python.find_installation('python3').full_path())
conf.set('VERSION', meson.project_version())
conf.set('APP_ID', app_id)
conf.set('BIN_NAME', bin_name)
conf.set('PREFIX', prefix)
conf.set('PROFILE', profile)
conf.set('LOCALE_DIR', get_option('prefix') / get_option('localedir'))
conf.set('BIN_DIR', get_option('prefix') / get_option('bindir'))

subdir('data')
subdir('showtime')
subdir('po')

meson.add_devenv({'SHOWTIME_SOURCE': meson.current_source_dir()})

gnome.post_install(
  glib_compile_schemas: true,
  gtk_update_icon_cache: true,
  update_desktop_database: true,
)
