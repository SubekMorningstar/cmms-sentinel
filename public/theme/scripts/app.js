(function ($) {
    'use strict';

    var THEMES = ['theme-dark', 'theme-default', 'theme-blue'];
    var mobileQuery = window.matchMedia('(max-width: 768px)');
    var panelTrigger = null;

    function isMobile() {
        return mobileQuery.matches;
    }

    function currentTheme() {
        var current = 'theme-dark';

        $.each(THEMES, function (_, theme) {
            if ($('body').hasClass(theme)) {
                current = theme;
            }
        });

        return current;
    }

    function syncColorScheme() {
        document.documentElement.style.colorScheme = currentTheme() === 'theme-dark' ? 'dark' : 'light';
    }

    function syncThemeButtons() {
        var theme = currentTheme();

        $('.theme-option').each(function () {
            var active = this.id === theme;

            $(this)
                .toggleClass('is-active', active)
                .attr('aria-pressed', active ? 'true' : 'false');
        });

        syncColorScheme();
    }

    function applyTheme(theme) {
        if (THEMES.indexOf(theme) === -1) {
            return;
        }

        $('body').removeClass(THEMES.join(' ')).addClass(theme);

        try {
            localStorage.setItem('cmms-theme', theme);
        } catch (e) {
            // Private mode can deny storage access; the theme still applies for this page load.
        }

        syncThemeButtons();
    }

    function navIsOpen() {
        return isMobile() && $('#sidebar').hasClass('open');
    }

    function panelIsOpen() {
        return $('#sidebar-right').hasClass('sidebar-open');
    }

    function closeNav() {
        $('#sidebar, .slide-sidebar-btn').removeClass('open');
    }

    function closePanel() {
        $('#sidebar-right').removeClass('sidebar-open');
    }

    function focusNavClose(showRing) {
        focusWithMode($('#sidebar .sidebar-close-btn'), showRing);
    }

    function focusWithMode($element, showRing) {
        if (!$element.length) {
            return;
        }

        $element.toggleClass('focus-silent', !showRing);
        $element.one('blur', function () {
            $(this).removeClass('focus-silent');
        });
        $element.trigger('focus');
    }

    function restorePanelFocus(showRing) {
        var $target = panelTrigger && panelTrigger.is(':visible')
            ? panelTrigger
            : $('.header .profile-panel-toggle').first();

        focusWithMode($target, showRing);
        panelTrigger = null;
    }

    function syncDrawerControls() {
        var navOpen = navIsOpen();
        var label = navOpen ? 'Tutup menu navigasi' : 'Buka menu navigasi';

        $('.slide-sidebar-btn').attr({
            'aria-expanded': navOpen ? 'true' : 'false',
            'aria-label': label,
            title: label
        });

        $('.profile-panel-toggle').not('.panel-close').attr('aria-expanded', panelIsOpen() ? 'true' : 'false');
    }

    function syncOverlay() {
        var nav = navIsOpen();
        var panel = panelIsOpen();

        $('#overlay')
            .toggleClass('is-visible', nav || panel)
            .toggleClass('overlay-nav', nav)
            .toggleClass('overlay-panel', !nav && panel);

        $('html').toggleClass('offcanvas-open', nav || (panel && isMobile()));

        syncDrawerControls();
    }

    function hideParentDropdown(element) {
        var $menuItem = $(element).closest('.menu-item');
        var $toggle = $menuItem.find('[data-toggle="dropdown"]').first();

        if ($toggle.length) {
            $toggle.dropdown('hide');
        }
    }

    $('body').on('click', '.switch-theme', function () {
        applyTheme(this.id);
    });

    $('body').on('click', '.slide-sidebar-btn', function (event) {
        if (navIsOpen()) {
            panelTrigger = null;
            closePanel();
            focusNavClose(event.detail === 0);
        }

        syncOverlay();
    });

    $('body').on('click', '.profile-panel-toggle', function (event) {
        event.preventDefault();

        if ($(this).hasClass('panel-close') || panelIsOpen()) {
            closePanel();
            syncOverlay();
            restorePanelFocus(event.detail === 0);
        } else {
            panelTrigger = $(this);
            closeNav();
            $('#sidebar-right').addClass('sidebar-open');
            hideParentDropdown(this);
            $(this).tooltip('hide');
            syncOverlay();
            focusWithMode($('#sidebar-right .panel-close'), event.detail === 0);
        }
    });

    $('#overlay').on('click', function () {
        var hadNav = navIsOpen();
        var hadPanel = panelIsOpen();

        closeNav();
        closePanel();
        syncOverlay();

        if (hadNav) {
            focusWithMode($('.slide-sidebar-btn'), false);
        } else if (hadPanel) {
            restorePanelFocus(false);
        }
    });

    $('body').on('click', '.sidebar-close-btn', function (event) {
        closeNav();
        syncOverlay();
        focusWithMode($('.slide-sidebar-btn'), event.detail === 0);
    });

    $(document).on('keydown', function (event) {
        if (event.key !== 'Escape' && event.keyCode !== 27) {
            return;
        }

        var hadNav = navIsOpen();
        var hadPanel = panelIsOpen();

        if (!hadNav && !hadPanel) {
            return;
        }

        closeNav();
        closePanel();
        syncOverlay();

        if (hadNav) {
            focusWithMode($('.slide-sidebar-btn'), true);
        } else {
            restorePanelFocus(true);
        }
    });

    function handleViewportChange() {
        if (!isMobile()) {
            closeNav();
        }

        syncOverlay();
    }

    if (typeof mobileQuery.addEventListener === 'function') {
        mobileQuery.addEventListener('change', handleViewportChange);
    } else if (typeof mobileQuery.addListener === 'function') {
        mobileQuery.addListener(handleViewportChange);
    }

    $(window).on('resize', syncOverlay);

    $(function () {
        syncThemeButtons();
        syncOverlay();
    });
})(jQuery);
