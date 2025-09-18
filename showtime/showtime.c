/*
 * SPDX-License-Identifier: GPL-3.0-or-later
 * SPDX-FileCopyrightText: Copyright 2025 Zander Brown <zbrown@gnome.org>
 */

#include "config.h"

#include <locale.h>

#include <glib/gi18n.h>
#include <glib.h>

#include <gtk/gtk.h>

#include <Python.h>


/* A module to hold our various constants */
static struct PyModuleDef module_def = {
  .m_base = PyModuleDef_HEAD_INIT,
  .m_name = "_showtime",
  .m_size = -1,
};


static PyObject*
PyInit_showtime (void)
{
  PyObject *module = PyModule_Create (&module_def);

  /* These values come from meson via config.h */
  PyModule_AddStringConstant (module, "APP_ID", G_STRINGIFY (APP_ID));
  PyModule_AddStringConstant (module, "BIN_NAME", G_STRINGIFY (BIN_NAME));
  PyModule_AddStringConstant (module, "LOCALE_DIR", G_STRINGIFY (LOCALE_DIR));
  PyModule_AddStringConstant (module, "PREFIX", G_STRINGIFY (PREFIX));
  PyModule_AddStringConstant (module, "PROFILE", G_STRINGIFY (PROFILE));
  PyModule_AddStringConstant (module, "VERSION", G_STRINGIFY (VERSION));

  return module;
}


static inline void
initialize_python (void)
{
  PyConfig config;
  PyStatus status;

  PyConfig_InitPythonConfig (&config);

  status = PyConfig_SetBytesString (&config,
                                    &config.program_name,
                                    G_STRINGIFY (BIN_NAME));
  if (PyStatus_Exception (status)) {
    goto exception;
  }

  /* Inject our constants */
  PyImport_AppendInittab ("_showtime", &PyInit_showtime);

  status = Py_InitializeFromConfig (&config);
  if (PyStatus_Exception (status)) {
    goto exception;
  }

  PyConfig_Clear (&config);

  return;

exception:
  PyConfig_Clear (&config);

  /* Prints exception and aborts */
  Py_ExitStatusException (status);
}


static inline void
handle_uninstalled_build (void)
{
  g_autoptr (GError) error = NULL;
  g_autofree char *source_utf8 = NULL;
  PyObject *path;
  PyObject *source_py = NULL;
  const char *source_fs = g_getenv ("SHOWTIME_SOURCE");
  size_t length = 0;

  /* Most of the time we have nothing to do here */
  if (G_LIKELY (!source_fs || strlen (source_fs) < 1)) {
    return;
  }

  /* In practice non-UTF8 is rather unlikely, but lets do this right */
  source_utf8 = g_filename_to_utf8 (source_fs, -1, NULL, &length, &error);
  if (error) {
    /* g_error aborts the process */
    g_error ("Non-UTF8 compatible path! %s", error->message);
    return;
  }

  g_debug ("Running from %s", source_utf8);

  source_py = PyUnicode_FromStringAndSize (source_utf8, length);

  path = PySys_GetObject ("path");
  PyList_Insert (path, 0, source_py);

  Py_XDECREF (source_py);
}


static inline PyObject *
argv_as_tuple (int argc, char *argv[])
{
  PyObject *tuple = PyTuple_New (argc);

  for (int i  = 0; i < argc; i++) {
    PyTuple_SetItem (tuple, i, PyBytes_FromString (argv[i]));
  }

  return tuple;
}


int
main (int argc, char *argv[])
{
  PyObject *module_name = NULL;
  PyObject *module = NULL;
  PyObject *entry = NULL;
  PyObject *args = NULL;
  PyObject *result = NULL;
  int res = EXIT_FAILURE;

  /* First, setup localisation in C */
  setlocale (LC_ALL, "");
  bindtextdomain (G_STRINGIFY (BIN_NAME), G_STRINGIFY (LOCALE_DIR));
  bind_textdomain_codeset (G_STRINGIFY (BIN_NAME), "UTF-8");
  textdomain (G_STRINGIFY (BIN_NAME));

  /* Prepare GLib/Gtk environment */
  g_set_prgname (G_STRINGIFY (BIN_NAME));
  g_set_application_name (_("Video Player"));
  gtk_window_set_default_icon_name (G_STRINGIFY (APP_ID));

  /* Fire up Python */
  initialize_python ();

  /* If running from source, add the tree to path */
  handle_uninstalled_build ();

  module_name = PyUnicode_FromString ("showtime");
  module = PyImport_Import (module_name);
  if (!module) {
    g_critical ("Bad Python module");
    PyErr_Print ();
    goto out;
  }

  entry = PyObject_GetAttrString (module, "main");
  if (!entry) {
    g_critical ("Entry-point missing");
    PyErr_Print ();
    goto out;
  }

  /* We pass argv in a tuple, and expect an int in return */
  args = Py_BuildValue ("(N)", argv_as_tuple (argc, argv));
  result = PyObject_CallObject (entry, args);
  if (!result) {
    g_critical ("Uncaught error");
    PyErr_Print ();
    goto out;
  }

  if (!PyLong_Check (result)) {
    PyObject *repr = PyObject_Repr (result);
    g_critical ("Expected int, got %s", PyUnicode_AsUTF8 (repr));
    goto out;
  }

  res = PyLong_AsLong (result);

out:
  Py_XDECREF (module_name);
  Py_XDECREF (module);
  Py_XDECREF (entry);
  Py_XDECREF (args);
  Py_XDECREF (result);

  return res;
}
