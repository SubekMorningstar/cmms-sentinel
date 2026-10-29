@php($user = auth()->user())

<header class="header">
    <div class="header-bar">
        <div class="brand">
            <a href="{{ route('dashboard') }}" class="logo" aria-label="CMMS - Dashboard">
                <span class="text-carolina">CMMS</span><span class="brand-sub">Condition Monitoring</span>
            </a>
        </div>
        <div class="btn-toggle">
            <a href="#" class="toggle-sidebar-btn" title="Perkecil atau perbesar sidebar"
                aria-label="Perkecil atau perbesar sidebar">
                <i class="ti-arrow-circle-left"></i>
            </a>
            <a href="#" class="slide-sidebar-btn" title="Buka menu navigasi" aria-label="Buka menu navigasi"
                aria-controls="sidebar" aria-expanded="false">
                <i class="ti-menu"></i>
            </a>
        </div>
        <div class="navigation d-flex align-items-center">
            <span class="status-pill d-none d-xl-inline-flex" data-toggle="tooltip"
                title="Gateway IoT belum terhubung. Integrasi data sensor dilakukan pada tahap berikutnya.">
                <span class="status-dot"></span> Gateway standby
            </span>
            <div class="navbar-menu d-flex">
                <div class="menu-item">
                    <a href="#" class="btn" data-toggle="dropdown" aria-haspopup="true" aria-expanded="false"
                        aria-label="Peringatan sensor">
                        <i class="ti-bell"></i>
                    </a>
                    <ul class="dropdown-menu dropdown-menu-right dropdown-alert">
                        <li class="dropdown-header text-center">
                            <a href="{{ route('dashboard') }}"><i class="ti-bell"></i> Pusat Peringatan
                                <i class="ti-angle-right"></i></a>
                        </li>
                        <li><a href="javascript:;"><i class="fa fa-check-circle"></i> Belum ada peringatan
                                <span>&mdash;</span></a></li>
                    </ul>
                </div>
                <div class="menu-item">
                    <a href="#" class="btn profile-panel-toggle" data-toggle="tooltip" title="Profil & tema"
                        aria-label="Buka panel profil dan tema" aria-controls="sidebar-right" aria-expanded="false">
                        <i class="ti-settings"></i>
                    </a>
                </div>
                <div class="menu-item">
                    <a href="#" class="btn btn-user" data-toggle="dropdown" aria-haspopup="true" aria-expanded="false"
                        aria-label="Menu pengguna">
                        <span class="avatar-initial">{{ $user->initials }}</span>
                    </a>
                    <ul class="dropdown-menu dropdown-menu-right dropdown-user">
                        <li class="dropdown-header text-left">
                            <strong>{{ $user->nama_lengkap }}</strong><br>
                            <small>{{ $user->role_label }} &middot; {{ $user->email }}</small>
                        </li>
                        <li>
                            <a href="#" class="profile-panel-toggle" aria-controls="sidebar-right"
                                aria-expanded="false"><i class="ti-user"></i> Profil &amp; Tema</a>
                        </li>
                        <li>
                            <form method="POST" action="{{ route('logout') }}">
                                @csrf
                                <button type="submit" class="dropdown-item text-danger"><i class="ti-power-off"></i>
                                    Keluar</button>
                            </form>
                        </li>
                    </ul>
                </div>
            </div>
        </div>
    </div>
</header>
