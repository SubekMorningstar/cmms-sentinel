<script>
    (function () {
        var themes = ['theme-dark', 'theme-default', 'theme-blue'];
        var theme = 'theme-dark';

        try {
            var saved = localStorage.getItem('cmms-theme');
            if (themes.indexOf(saved) !== -1) {
                theme = saved;
            }
        } catch (e) { }

        document.body.className = theme;
        document.documentElement.style.colorScheme = theme === 'theme-dark' ? 'dark' : 'light';
    })();
</script>
