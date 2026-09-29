from datetime import date, datetime
from decimal import Decimal as D

import pytest
from django.urls import reverse

from apps.auditoria.models import Accion, RegistroAuditoria
from apps.nomina import cheques, deposito_directo, nacha, servicios
from apps.nomina.models import ArchivoBancario, ConfiguracionNACHA

from .conftest import crear_empleado
from .test_nomina import compania_lista, entrar_horas, periodo_semana  # noqa: F401

RUTA_BANCO = "021502011"
RUTA_EMP = "011000015"
RUTA_EMP2 = "021000021"


def _origen(**extra):
    return nacha.Origen(ruta_banco=RUTA_BANCO, nombre_banco="Banco Popular", origen_inmediato="1660123456",
                        identificacion_compania="1660123456", nombre_compania="Restaurante Ñandú", **extra)


def _pagos():
    return [nacha.Pago(RUTA_EMP, "123456789", "cheques", D("420.36"), "1", "José Martínez"),
            nacha.Pago(RUTA_EMP2, "98765", "ahorros", D("1000.00"), "2", "Ana del Pueblo")]


def test_estructura_del_archivo():
    texto = nacha.generar(_origen(), _pagos(), date(2026, 9, 18), datetime(2026, 9, 16, 14, 30))
    lineas = texto.split("\r\n")[:-1]
    assert all(len(l) == 94 for l in lineas) and len(lineas) % 10 == 0
    assert [l[0] for l in lineas[:6]] == ["1", "5", "6", "6", "8", "9"]
    assert set(lineas[6:]) == {"9" * 94}
    cab = lineas[0]
    assert cab[3:13] == " " + RUTA_BANCO and cab[13:23] == "1660123456" and cab[23:29] == "260916"
    assert cab[63:86].rstrip() == "RESTAURANTE NANDU"
    lote = lineas[1]
    assert lote[1:4] == "220" and lote[50:53] == "PPD" and lote[53:63] == "NOMINA    " and lote[69:75] == "260918"
    assert lote[79:87] == RUTA_BANCO[:8] and lote[87:94] == "0000001"
    e1, e2 = lineas[2], lineas[3]
    assert e1[1:3] == "22" and e1[3:12] == RUTA_EMP and e1[12:29] == "123456789".ljust(17)
    assert e1[29:39] == "0000042036" and e1[54:76] == "JOSE MARTINEZ".ljust(22) and e1[78] == "0"
    assert e1[79:94] == RUTA_BANCO[:8] + "0000001"
    assert e2[1:3] == "32" and e2[29:39] == "0000100000" and e2[79:94].endswith("0000002")
    control = lineas[4]
    hash_ = str(int(RUTA_EMP[:8]) + int(RUTA_EMP2[:8])).zfill(10)
    assert control[4:10] == "000002" and control[10:20] == hash_
    assert control[20:32] == "0" * 12 and control[32:44] == "000000142036"
    fin = lineas[5]
    assert fin[1:7] == "000001" and fin[7:13] == "000001" and fin[13:21] == "00000002" and fin[21:31] == hash_
    assert fin[43:55] == "000000142036"


def test_archivo_balanceado():
    origen = _origen(balanceado=True, ruta_compania=RUTA_BANCO, cuenta_compania="555000111")
    lineas = nacha.generar(origen, _pagos(), date(2026, 9, 18), datetime(2026, 9, 16)).split("\r\n")
    assert lineas[1][1:4] == "200"
    debito = lineas[4]
    assert debito[1:3] == "27" and debito[29:39] == "0000142036"
    control = lineas[5]
    assert control[1:4] == "200" and control[4:10] == "000003" and control[20:32] == control[32:44] == "000000142036"


def test_validaciones():
    with pytest.raises(nacha.ErrorNACHA, match="ruta inválido"):
        nacha.generar(_origen(), [nacha.Pago("123456789", "1", "cheques", D("1"), "1", "X")], date(2026, 9, 18),
                      datetime(2026, 9, 16))
    with pytest.raises(nacha.ErrorNACHA, match="No hay"):
        nacha.generar(_origen(), [], date(2026, 9, 18), datetime(2026, 9, 16))
    with pytest.raises(nacha.ErrorNACHA, match="cuenta de la compañía"):
        nacha.generar(_origen(balanceado=True, ruta_compania=RUTA_BANCO), _pagos(), date(2026, 9, 18),
                      datetime(2026, 9, 16))


@pytest.fixture
def nomina_con_depositos(compania_lista, preparador):  # noqa: F811
    ana = crear_empleado(compania_lista, numero="1", ssn="234567890", nombre="Ana", tarifa="12")
    beto = crear_empleado(compania_lista, numero="2", ssn="345678901", nombre="Beto", tarifa="15")
    carla = crear_empleado(compania_lista, numero="3", ssn="456789012", nombre="Carla", tarifa="20")
    for emp, cuenta in ((ana, "111122223333"), (beto, "444455556666")):
        emp.deposito_directo = True
        emp.banco_nombre = "Banco X"
        emp.banco_ruta = RUTA_EMP
        emp.asignar_cuenta_bancaria(cuenta)
        emp.save()
    periodo = periodo_semana(compania_lista, preparador)
    for e in (ana, beto, carla):
        entrar_horas(periodo, e, horas_regulares="40")
    servicios.calcular_periodo(periodo, preparador)
    servicios.cerrar_periodo(periodo, preparador)
    ConfiguracionNACHA.objects.create(compania=compania_lista, nombre_banco="Banco Popular", ruta_banco=RUTA_BANCO,
                                      origen_inmediato="1660123456", identificacion_compania="1660123456",
                                      nombre_compania="Restaurante")
    return periodo, ana, beto, carla


@pytest.mark.django_db
def test_generar_desde_nomina(nomina_con_depositos, preparador):
    periodo, ana, beto, carla = nomina_con_depositos
    # A Beto se le pagó con cheque esta vez: no va en el archivo.
    cheques.emitir(periodo, [periodo.resultados.get(empleado=beto)], 100, preparador)
    assert [r.empleado_id for r in deposito_directo.depositos(periodo)] == [ana.pk]
    assert deposito_directo.fecha_efectiva_sugerida(periodo) == date(2026, 9, 18)
    with pytest.raises(deposito_directo.ErrorDeposito, match="laborable"):
        deposito_directo.generar(periodo, date(2026, 9, 19), preparador)
    texto, archivo = deposito_directo.generar(periodo, date(2026, 9, 18), preparador)
    neto = periodo.resultados.get(empleado=ana).neto
    assert "111122223333" in texto and "444455556666" not in texto
    assert archivo.depositos == 1 and archivo.total == neto and len(archivo.huella) == 64


@pytest.mark.django_db
def test_pantallas_y_permisos(cliente_preparador, cliente_admin, cliente_lectura, nomina_con_depositos):
    periodo, *_ = nomina_con_depositos
    url = reverse("nomina:deposito_directo", args=[periodo.pk])
    assert cliente_lectura.get(url).status_code == 403
    html = cliente_preparador.get(url).content.decode()
    assert "••••3333" in html and "111122223333" not in html
    respuesta = cliente_preparador.post(url, {"fecha_efectiva": "2026-09-18"})
    assert respuesta["Content-Disposition"].startswith('attachment; filename="NOMINA_20260918.ach"')
    assert b"111122223333" in respuesta.content
    assert ArchivoBancario.objects.count() == 1
    assert RegistroAuditoria.objects.filter(accion=Accion.ARCHIVO_GENERADO, descripcion__startswith="Archivo NACHA").exists()
    assert "Ya se generó" in cliente_preparador.get(url).content.decode()

    config_url = reverse("nomina:configuracion_nacha")
    assert cliente_preparador.get(config_url).status_code == 403
    datos = {"nombre_banco": "Banco Popular", "ruta_banco": RUTA_BANCO, "origen_inmediato": "1660123456",
             "identificacion_compania": "1660123456", "nombre_compania": "Restaurante", "descripcion": "NOMINA",
             "tipo_cuenta_compania": "cheques", "balanceado": "on", "ruta_compania": RUTA_BANCO}
    malo = cliente_admin.post(config_url, datos)
    assert "necesita la cuenta" in malo.content.decode()
    cliente_admin.post(config_url, {**datos, "cuenta_compania_nueva": "555000111"})
    config = ConfiguracionNACHA.objects.get()
    assert config.balanceado and config.cuenta_compania.revelar() == "555000111"
    assert config.cuenta_compania_ultimos4 == "0111"
    registro = RegistroAuditoria.objects.filter(accion=Accion.CONFIG_NACHA).latest("id")
    assert "555000111" not in str(registro.cambios)
