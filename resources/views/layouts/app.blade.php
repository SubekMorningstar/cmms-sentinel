<!DOCTYPE html>
<html lang="id">

<head>
    <meta charset="utf-8" />
    <meta http-equiv="X-UA-Compatible" content="IE=edge" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />

    <title>@yield('title', 'Dashboard') &middot; {{ config('app.name') }}</title>

    @include('partials.styles')
    @stack('styles')
</head>

<body class="theme-dark">
    @include('partials.theme-init')

    <a class="skip-link" href="#main-content">Lewati ke konten utama</a>

    <div class="grid-wrapper">

        @include('partials.header')
        @include('partials.sidebar')

        <main class="main" id="main-content" tabindex="-1">
            @yield('breadcrumbs')
            @yield('content')
        </main>

        @include('partials.footer')
        @include('partials.aside-right')

        <div id="overlay"></div>

    </div>

    @include('partials.scripts')
    @stack('scripts')
</body>

</html>
