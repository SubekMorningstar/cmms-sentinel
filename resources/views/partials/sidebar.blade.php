@php($user = auth()->user())

<nav id="sidebar" class="sidebar" aria-label="Navigasi utama">
    <div class="sidebar-mobile-head">
        <span>Menu Navigasi</span>
        <button type="button" class="sidebar-close-btn" aria-label="Tutup menu navigasi">
            <i class="ti-close"></i>
        </button>
    </div>
    <div class="sidebar-content">
        <div class="sidebar-menu">
            <ul>
                <li class="header-menu">Monitoring</li>
                <li class="{{ request()->routeIs('dashboard') ? 'active' : '' }}">
                    <a href="{{ route('dashboard') }}" title="Dashboard"
                        @if (request()->routeIs('dashboard')) aria-current="page" @endif>
                        <i class="ti-dashboard"></i>
                        <span class="menu-text">Dashboard</span>
                    </a>
                </li>
                <li class="{{ request()->routeIs('cbm.*') ? 'active' : '' }}">
                    <a href="{{ route('cbm.index') }}" title="Condition Monitoring"
                        @if (request()->routeIs('cbm.*')) aria-current="page" @endif>
                        <i class="ti-pulse"></i>
                        <span class="menu-text">Condition Monitoring</span>
                    </a>
                </li>

                @if ($user->isAdmin())
                    <li class="header-menu">Master Data</li>
                    <li class="{{ request()->routeIs('assets.*') ? 'active' : '' }}">
                        <a href="{{ route('assets.index') }}" title="Assets / Mesin"
                            @if (request()->routeIs('assets.*')) aria-current="page" @endif>
                            <i class="ti-harddrives"></i>
                            <span class="menu-text">Assets / Mesin</span>
                        </a>
                    </li>
                    <li class="{{ request()->routeIs('thresholds.*') ? 'active' : '' }}">
                        <a href="{{ route('thresholds.index') }}" title="Threshold Sensor"
                            @if (request()->routeIs('thresholds.*')) aria-current="page" @endif>
                            <i class="ti-settings"></i>
                            <span class="menu-text">Threshold Sensor</span>
                        </a>
                    </li>
                @endif

                <li class="header-menu">Perawatan</li>
                <li class="{{ request()->routeIs('work-orders.*') ? 'active' : '' }}">
                    <a href="{{ route('work-orders.index') }}" title="Work Orders"
                        @if (request()->routeIs('work-orders.*')) aria-current="page" @endif>
                        <i class="ti-clipboard"></i>
                        <span class="menu-text">Work Orders</span>
                    </a>
                </li>
            </ul>
        </div>
    </div>
</nav>
