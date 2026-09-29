from datetime import date
from decimal import Decimal as D

import pytest
from django.urls import reverse

from apps.auditoria.models import Accion, RegistroAuditoria
from apps.nomina import cheques, servicios
from apps.nomina.models import Cheque, ErrorChequeInmutable, FormatoCheque

from .conftest import crear_empleado
from .test_nomina import compania_lista, entrar_horas, periodo_semana  # noqa: F401


@pytest.fixture
def nomina_cerrada(compania_lista, preparador):  # noqa: F811
    ana = crear_empleado(compania_lista, numero="1", ssn="234567890", nombre="Ana", tarifa="12",
                         direccion_linea1="Calle 1", ciudad="Ponce", codigo_postal="00731")
    beto = crear_empleado(compania_lista, numero="2", ssn="345678901", nombre="Beto", tarifa="15")
    carla = crear_empleado(compania_lista, numero="3", ssn="456789012", nombre="Carla", tarifa="20")
    carla.deposito_directo = True
    carla.banco_nombre = "Banco X"
    carla.banco_ruta = "021502011"
    carla.asignar_cuenta_bancaria("123456789")
    carla.save()
    periodo = periodo_semana(compania_lista, preparador)
    for e in (ana, beto, carla):
        entrar_horas(periodo, e, horas_regulares="40")
    servicios.calcular_periodo(periodo, preparador)
    servicios.cerrar_periodo(periodo, preparador)
    return periodo


def _res(periodo, nombre):
    return periodo.resultados.get(empleado_nombre__startswith=nombre)


@pytest.mark.django_db
def test_emitir_numera_en_orden_y_avanza_el_formato(nomina_cerrada, preparador):
    p = nomina_cerrada
    sugeridos = [r for r in p.resultados.all() if cheques.por_cheque_sugerido(r)]
    assert sorted(r.empleado_nombre[:4] for r in sugeridos) == ["Ana ", "Beto"]
    emitidos = cheques.emitir(p, sugeridos, 5001, preparador)
    assert [(c.numero, c.beneficiario[:4], c.fecha) for c in emitidos] == [
        (5001, "Ana ", p.fecha_pago), (5002, "Beto", p.fecha_pago)]
    assert emitidos[0].monto == _res(p, "Ana").neto
    assert FormatoCheque.objects.get(compania=p.compania).siguiente_numero == 5003
    # No se emite dos veces al mismo empleado ni se repite un número.
    with pytest.raises(cheques.ErrorCheque, match="ya tiene"):
        cheques.emitir(p, [_res(p, "Ana")], 6000, preparador)
    with pytest.raises(cheques.ErrorCheque, match="5002 ya se usaron"):
        cheques.emitir(p, [_res(p, "Carla")], 5002, preparador)


@pytest.mark.django_db
def test_solo_nomina_cerrada(compania_lista, preparador):  # noqa: F811
    e = crear_empleado(compania_lista, tarifa="12")
    periodo = periodo_semana(compania_lista, preparador)
    entrar_horas(periodo, e, horas_regulares="40")
    servicios.calcular_periodo(periodo, preparador)
    with pytest.raises(cheques.ErrorCheque, match="cerrada"):
        cheques.emitir(periodo, list(periodo.resultados.all()), 1, preparador)


@pytest.mark.django_db
def test_cheque_inmutable_anular_y_reemitir(nomina_cerrada, preparador):
    p = nomina_cerrada
    cheque = cheques.emitir(p, [_res(p, "Ana")], 100, preparador)[0]
    cheque.monto = D("1")
    with pytest.raises(ErrorChequeInmutable):
        cheque.save()
    with pytest.raises(ErrorChequeInmutable):
        Cheque.objects.get(pk=cheque.pk).delete()
    cheque.refresh_from_db()
    with pytest.raises(cheques.ErrorCheque, match="motivo"):
        cheques.anular(cheque, " ", preparador)
    nuevo = cheques.reemitir(cheque, "Se atascó en la impresora", preparador)
    cheque.refresh_from_db()
    assert cheque.estado == "anulado" and cheque.anulado_por == preparador
    assert nuevo.numero == 101 and nuevo.monto == cheque.monto and nuevo.estado == "emitido"
    anulado = Cheque.objects.get(pk=cheque.pk)
    anulado.estado = "emitido"
    with pytest.raises(ErrorChequeInmutable):
        anulado.save()


@pytest.mark.django_db
def test_reversar_anula_los_cheques(nomina_cerrada, preparador, admin):
    p = nomina_cerrada
    cheque = cheques.emitir(p, [_res(p, "Ana")], 7, preparador)[0]
    servicios.reversar_periodo(p, "Horas equivocadas", admin)
    cheque.refresh_from_db()
    assert cheque.estado == "anulado" and "Horas equivocadas" in cheque.motivo_anulacion


@pytest.mark.django_db
def test_pantalla_emitir_imprimir_anular(cliente_preparador, nomina_cerrada):
    p = nomina_cerrada
    url = reverse("nomina:cheques", args=[p.pk])
    html = cliente_preparador.get(url).content.decode()
    assert "Emitir cheques" in html and "1001" in html
    ana, beto = _res(p, "Ana"), _res(p, "Beto")
    cliente_preparador.post(url, {"accion": "emitir", "primer_numero": "2001", f"r_{ana.pk}": "on", f"r_{beto.pk}": "on"})
    assert list(Cheque.objects.values_list("numero", flat=True)) == [2001, 2002]
    assert RegistroAuditoria.objects.filter(accion=Accion.CHEQUE_EMITIDO).exists()

    pdf = cliente_preparador.get(reverse("nomina:cheques_pdf", args=[p.pk]))
    assert pdf["Content-Type"] == "application/pdf" and pdf.content.startswith(b"%PDF")
    uno = cliente_preparador.get(reverse("nomina:cheques_pdf", args=[p.pk]) + "?cheque=2002")
    assert uno.status_code == 200
    avisos = cliente_preparador.get(reverse("nomina:avisos_deposito", args=[p.pk]))
    assert avisos.content.startswith(b"%PDF")

    cheque = Cheque.objects.get(numero=2001)
    cliente_preparador.post(url, {"accion": "reemitir", "cheque": cheque.pk, "motivo": "Dañado"})
    assert Cheque.objects.get(numero=2001).estado == "anulado"
    assert Cheque.objects.get(numero=2003).resultado == ana
    assert RegistroAuditoria.objects.filter(accion=Accion.CHEQUE_ANULADO).exists()
    html = cliente_preparador.get(url).content.decode()
    assert "Anulado" in html and "Dañado" in html


@pytest.mark.django_db
def test_permisos_y_aislamiento(cliente_lectura, cliente_preparador, nomina_cerrada, preparador, otra_compania, admin):
    p = nomina_cerrada
    cheques.emitir(p, [_res(p, "Ana")], 10, preparador)
    assert cliente_lectura.get(reverse("nomina:cheques", args=[p.pk])).status_code == 200
    assert cliente_lectura.get(reverse("nomina:cheques_pdf", args=[p.pk])).status_code == 403
    assert cliente_lectura.post(reverse("nomina:cheques", args=[p.pk]), {"accion": "emitir"}).status_code == 403
    assert cliente_lectura.get(reverse("nomina:formato_cheque")).status_code == 403
    ajeno = servicios.crear_periodo(compania=otra_compania, inicio=date(2026, 9, 7), fin=date(2026, 9, 13),
                                    fecha_pago=date(2026, 9, 18), usuario=admin)
    assert cliente_preparador.get(reverse("nomina:cheques", args=[ajeno.pk])).status_code == 404
    assert cliente_preparador.get(reverse("nomina:cheques_pdf", args=[ajeno.pk])).status_code == 404


@pytest.mark.django_db
def test_formato_y_prueba_de_alineacion(cliente_preparador, compania_lista):  # noqa: F811
    url = reverse("nomina:formato_cheque")
    assert cliente_preparador.get(url).status_code == 200
    respuesta = cliente_preparador.post(url, {"posicion": "abajo", "idioma": "en", "siguiente_numero": "3500",
                                              "ajuste_horizontal": "0.10", "ajuste_vertical": "-0.05",
                                              "nombre_cuenta": "Banco X Nómina"})
    assert respuesta.status_code == 302
    formato = FormatoCheque.objects.get(compania=compania_lista)
    assert (formato.posicion, formato.siguiente_numero, formato.ajuste_vertical) == ("abajo", 3500, D("-0.05"))
    assert RegistroAuditoria.objects.filter(accion=Accion.FORMATO_CHEQUE).exists()
    malo = cliente_preparador.post(url, {"posicion": "arriba", "idioma": "es", "siguiente_numero": "1",
                                         "ajuste_horizontal": "5", "ajuste_vertical": "0"})
    assert malo.status_code == 200
    prueba = cliente_preparador.get(reverse("nomina:prueba_alineacion"))
    assert prueba.content.startswith(b"%PDF")


@pytest.mark.django_db
@pytest.mark.parametrize("posicion", ["arriba", "medio", "abajo"])
def test_pdf_en_cada_posicion(nomina_cerrada, preparador, posicion):
    from apps.nomina import pdf_cheques

    p = nomina_cerrada
    formato = cheques.formato_de(p.compania)
    formato.posicion = posicion
    formato.imprimir_encabezado = True
    formato.save()
    emitidos = cheques.emitir(p, [_res(p, "Ana"), _res(p, "Beto")], 1, preparador)
    contenido = pdf_cheques.generar_cheques(formato, emitidos)
    assert contenido.startswith(b"%PDF") and len(contenido) > 2000
