import io

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.companias.models import Compania
from apps.nomina.models import Cheque, PeriodoNomina


@pytest.mark.django_db
def test_cargar_demo(admin):
    call_command("cargar_demo", stdout=io.StringIO())
    c = Compania.objects.get(nombre="Restaurante La Ceiba, LLC")
    assert c.empleados.count() == 6
    assert PeriodoNomina.objects.filter(compania=c, estado="cerrada").count() == 3
    assert PeriodoNomina.objects.filter(compania=c, estado="calculada").count() == 1
    assert Cheque.objects.filter(compania=c).exists()
    with pytest.raises(CommandError, match="ya están cargados"):
        call_command("cargar_demo")


@pytest.mark.django_db
def test_demo_requiere_admin_y_no_va_en_produccion(settings):
    with pytest.raises(CommandError, match="createsuperuser"):
        call_command("cargar_demo")
    settings.PRODUCCION = True
    with pytest.raises(CommandError, match="producción"):
        call_command("cargar_demo")
