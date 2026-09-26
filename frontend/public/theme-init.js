// Apply the saved or system theme before first paint to avoid a flash of the wrong theme.
(function () {
  var t
  try { t = localStorage.getItem('options-screener-theme') } catch (e) {}
  if (t !== 'light' && t !== 'dark') t = matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark'
  document.documentElement.dataset.theme = t
  var p
  try { p = localStorage.getItem('options-screener-palette') } catch (e) {}
  document.documentElement.dataset.palette = /^(dial|terminal|bankers|ultraviolet|petrol)$/.test(p || '') ? p : 'dial'
})()
