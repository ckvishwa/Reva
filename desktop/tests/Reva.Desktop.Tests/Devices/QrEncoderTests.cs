using Reva.Desktop.Devices;

namespace Reva.Desktop.Tests.Devices;

public class QrEncoderTests
{
    private static readonly byte[] PngSignature = { 0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A };

    // A payload the size of a real pairing code: prefix + base64url of the JSON Core builds.
    private static string RealisticPayload() =>
        "REVA-PAIR1:" + Convert.ToBase64String(System.Text.Encoding.UTF8.GetBytes(
            """{"code":"AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA","exp":1800000120,"gw":"0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef","host":"192.168.100.200","port":47821,"v":1}"""))
            .TrimEnd('=').Replace('+', '-').Replace('/', '_');

    [Fact]
    public void A_real_sized_pairing_payload_becomes_a_png()
    {
        var png = new QrCoderEncoder().EncodePng(RealisticPayload());

        Assert.True(png.Length > 500);
        Assert.Equal(PngSignature, png.Take(8).ToArray());
    }

    [Fact]
    public void The_same_text_gives_the_same_image_and_different_text_a_different_one()
    {
        var encoder = new QrCoderEncoder();
        var one = encoder.EncodePng(RealisticPayload());

        Assert.Equal(one, encoder.EncodePng(RealisticPayload()));
        Assert.NotEqual(one, encoder.EncodePng(RealisticPayload() + "x"));
    }

    [Fact]
    public void The_image_is_large_enough_to_scan_from_a_phone_camera()
    {
        var png = new QrCoderEncoder().EncodePng(RealisticPayload());

        // IHDR width/height are big-endian ints at bytes 16 and 20.
        var width = (png[16] << 24) | (png[17] << 16) | (png[18] << 8) | png[19];
        var height = (png[20] << 24) | (png[21] << 16) | (png[22] << 8) | png[23];
        Assert.Equal(width, height);
        Assert.InRange(width, 200, 1000); // 8 px per module, a version-7 to 10 code plus its quiet zone
    }
}
