<div class="row">
    <div class="col">
        <ol class="breadcrumb" aria-label="Breadcrumb">
            <li class="breadcrumb-item"><a href="{{ route('dashboard') }}"><i class="ti-home"></i> Dashboard</a></li>
            @foreach ($items as $label => $url)
                @if ($url)
                    <li class="breadcrumb-item"><a href="{{ $url }}">{{ $label }}</a></li>
                @else
                    <li class="breadcrumb-item active" aria-current="page">{{ $label }}</li>
                @endif
            @endforeach
        </ol>
    </div>
</div>
